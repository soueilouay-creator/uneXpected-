from __future__ import annotations

import hashlib
import html.parser
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import time
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit


_DNS_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="unexpected-source-dns")


class SourceRetrievalError(ValueError):
    """A source could not be safely retrieved and verified."""


def _normalize_domain(value: str) -> str:
    if not isinstance(value, str):
        raise SourceRetrievalError("Allowed source domains must be hostnames.")
    candidate = value.strip().lower()
    if not candidate or candidate.endswith(".") or "*" in candidate:
        raise SourceRetrievalError("Allowed source domains must be exact hostnames without wildcards.")
    try:
        host = candidate.encode("idna").decode("ascii")
    except UnicodeError:
        raise SourceRetrievalError("Allowed source domain is not valid IDNA.") from None
    if (
        len(host) > 253
        or "." not in host
        or host.rsplit(".", 1)[-1] in {"localhost", "local", "internal", "test", "invalid", "example", "onion"}
        or not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))+", host)
    ):
        raise SourceRetrievalError("Allowed source domains must be public-looking exact DNS hostnames.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise SourceRetrievalError("IP literals are not permitted in the source allowlist.")


def _resolve_public_addresses(host: str, port: int) -> list[str]:
    try:
        future = _DNS_POOL.submit(socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM)
        results = future.result(timeout=4)
    except FutureTimeout:
        raise SourceRetrievalError("Source host DNS lookup exceeded its deadline.") from None
    except OSError:
        raise SourceRetrievalError("Source host DNS lookup failed.") from None
    addresses: list[str] = []
    for result in results:
        address = result[4][0]
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError:
            raise SourceRetrievalError("Source host returned an invalid network address.") from None
        if not parsed.is_global:
            raise SourceRetrievalError("Source host resolved to a non-public network address.")
        normalized = str(parsed)
        if normalized not in addresses:
            addresses.append(normalized)
    if not addresses:
        raise SourceRetrievalError("Source host did not resolve to a public address.")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TLS connection pinned to an already validated public IP address."""

    def __init__(self, host: str, address: str, timeout_seconds: float) -> None:
        super().__init__(host, port=443, timeout=timeout_seconds, context=ssl.create_default_context())
        self._pinned_address = address

    def connect(self) -> None:
        raw = socket.create_connection(
            (self._pinned_address, self.port),
            self.timeout,
            self.source_address,
        )
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _fetch_pinned_https(
    host: str,
    address: str,
    request_target: str,
    timeout_seconds: float,
    max_bytes: int,
) -> tuple[int, dict[str, str], bytes]:
    connection = _PinnedHTTPSConnection(host, address, timeout_seconds)
    try:
        connection.request(
            "GET",
            request_target,
            headers={
                "Host": host,
                "Accept": "text/html, application/xhtml+xml, text/plain, application/json",
                "Accept-Encoding": "identity",
                "Connection": "close",
                "User-Agent": "uneXpected-source-retriever/1.0",
            },
        )
        response = connection.getresponse()
        headers = {key.lower(): value for key, value in response.getheaders()}
        declared_length = headers.get("content-length")
        if declared_length is not None:
            try:
                declared_size = int(declared_length)
            except ValueError:
                raise SourceRetrievalError("Source response has an invalid content length.") from None
            if declared_size < 0 or declared_size > max_bytes:
                raise SourceRetrievalError("Source response exceeds the configured byte limit.")
        body = response.read(max_bytes + 1)
        return response.status, headers, body
    except SourceRetrievalError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError, TimeoutError):
        raise SourceRetrievalError("Source HTTPS request failed.") from None
    finally:
        connection.close()


class _VisibleHTMLText(html.parser.HTMLParser):
    _IGNORED = {"script", "style", "noscript", "svg", "iframe", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self._IGNORED:
            self._ignored_depth += 1
        elif tag == "title" and self._ignored_depth == 0:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._IGNORED and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        clean = data.strip()
        if clean:
            if self._in_title:
                self.title_parts.append(clean)
            self.text_parts.append(clean)


def _select_excerpt(text: str, max_chars: int) -> str:
    """Prefer a bounded passage near test-discovery material when present."""
    patterns = (
        r"unittest supports simple test discovery",
        r"when executed without arguments.{0,100}discovery",
        r"test\s+discovery",
        r"discovery",
        r"discovering",
        r"find.{0,80}tests",
    )
    match = None
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match is not None:
            break
    if match is None or len(text) <= max_chars:
        return text[:max_chars]
    start = max(0, match.start() - max_chars // 3)
    end = min(len(text), start + max_chars)
    excerpt = text[start:end].strip()
    if start:
        excerpt = "… " + excerpt
    if end < len(text):
        excerpt = excerpt.rstrip() + " …"
    return excerpt[:max_chars]


class TrustedSourceRetriever:
    """Bounded HTTPS source retrieval for a caller-configured exact host allowlist.

    DNS is resolved before connecting and every result must be globally routable.
    The TCP connection uses the selected resolved IP while TLS still validates
    the original hostname, preventing a second DNS lookup from changing the
    destination after the security check.
    """

    def __init__(
        self,
        allowed_domains: list[str] | tuple[str, ...] | set[str],
        *,
        timeout_seconds: float = 8.0,
        max_bytes: int = 262144,
        max_sources: int = 3,
        max_excerpt_chars: int = 2400,
        resolver: Callable[[str, int], list[str]] | None = None,
        transport: Callable[[str, str, str, float, int], tuple[int, dict[str, str], bytes]] | None = None,
    ) -> None:
        if not isinstance(allowed_domains, (list, tuple, set)) or not allowed_domains:
            raise SourceRetrievalError("At least one exact source domain must be allowlisted.")
        self.allowed_domains = frozenset(_normalize_domain(item) for item in allowed_domains)
        if len(self.allowed_domains) != len(allowed_domains):
            raise SourceRetrievalError("The source allowlist contains duplicate domains.")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0.2 <= timeout_seconds <= 20:
            raise SourceRetrievalError("Source timeout must be between 0.2 and 20 seconds.")
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1024 <= max_bytes <= 1048576:
            raise SourceRetrievalError("Source byte limit must be between 1 KiB and 1 MiB.")
        if isinstance(max_sources, bool) or not isinstance(max_sources, int) or not 1 <= max_sources <= 5:
            raise SourceRetrievalError("Source count limit must be between 1 and 5.")
        if isinstance(max_excerpt_chars, bool) or not isinstance(max_excerpt_chars, int) or not 256 <= max_excerpt_chars <= 12000:
            raise SourceRetrievalError("Source excerpt limit must be between 256 and 12000 characters.")
        self.timeout_seconds = float(timeout_seconds)
        self.max_bytes = max_bytes
        self.max_sources = max_sources
        self.max_excerpt_chars = max_excerpt_chars
        self._resolver = resolver or _resolve_public_addresses
        self._transport = transport or _fetch_pinned_https

    def _parse_url(self, url: str) -> tuple[str, str]:
        if (
            not isinstance(url, str) or not url or len(url) > 2048
            or any(ord(character) < 0x20 or ord(character) == 0x7F for character in url)
        ):
            raise SourceRetrievalError("Source reference must be a safe URL of at most 2048 characters.")
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            raise SourceRetrievalError("Source URL is malformed.") from None
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or port not in (None, 443)
            or parsed.query
            or parsed.fragment
        ):
            raise SourceRetrievalError("Only credential-free HTTPS URLs on port 443 without query or fragment are accepted.")
        raw_host = parsed.hostname.lower()
        try:
            address_literal = ipaddress.ip_address(raw_host)
        except ValueError:
            address_literal = None
        if address_literal is not None:
            raise SourceRetrievalError("IP-literal source URLs are not permitted.")
        try:
            host = raw_host.encode("idna").decode("ascii")
        except UnicodeError:
            raise SourceRetrievalError("Source URL hostname is not valid IDNA.") from None
        if host not in self.allowed_domains:
            raise SourceRetrievalError("Source URL hostname is not in the configured allowlist.")
        path = parsed.path or "/"
        request_target = urlunsplit(("", "", path, "", ""))
        return host, request_target

    @staticmethod
    def _extract(content_type: str, body: bytes) -> tuple[str, str]:
        charset_match = re.search(r"charset=([\"']?)([a-zA-Z0-9._-]+)", content_type, re.IGNORECASE)
        charset = charset_match.group(2) if charset_match else "utf-8"
        try:
            decoded = body.decode(charset, errors="replace")
        except LookupError:
            decoded = body.decode("utf-8", errors="replace")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type in {"text/html", "application/xhtml+xml"}:
            parser = _VisibleHTMLText()
            parser.feed(decoded)
            parser.close()
            title = " ".join(parser.title_parts).strip()
            text = " ".join(parser.text_parts)
        elif media_type == "application/json":
            try:
                parsed = json.loads(decoded)
                title = ""
                text = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
            except json.JSONDecodeError:
                raise SourceRetrievalError("Source returned malformed JSON.") from None
        elif media_type == "text/plain":
            title = ""
            text = decoded
        else:
            raise SourceRetrievalError("Source returned an unsupported content type.")
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            raise SourceRetrievalError("Source returned no extractable text.")
        return title[:240], normalized

    def retrieve(self, url: str) -> dict[str, Any]:
        host, request_target = self._parse_url(url)
        addresses = self._resolver(host, 443)
        if not isinstance(addresses, list) or not addresses:
            raise SourceRetrievalError("Source host did not resolve to a public address.")
        validated: list[str] = []
        for address in addresses:
            try:
                parsed_address = ipaddress.ip_address(address)
            except ValueError:
                raise SourceRetrievalError("Source host returned an invalid network address.") from None
            if not parsed_address.is_global:
                raise SourceRetrievalError("Source host resolved to a non-public network address.")
            normalized = str(parsed_address)
            if normalized not in validated:
                validated.append(normalized)
        if len(validated) > 8:
            raise SourceRetrievalError("Source host returned too many network addresses.")
        deadline = time.monotonic() + self.timeout_seconds
        last_error: SourceRetrievalError | None = None
        for address in validated:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                status, headers, body = self._transport(
                    host, address, request_target, remaining, self.max_bytes,
                )
                break
            except SourceRetrievalError as exc:
                last_error = exc
        else:
            raise last_error or SourceRetrievalError("Source host could not be reached over HTTPS.")
        if status != 200:
            raise SourceRetrievalError(f"Source request returned HTTP {status}; redirects are not followed.")
        if len(body) > self.max_bytes:
            raise SourceRetrievalError("Source response exceeds the configured byte limit.")
        if headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
            raise SourceRetrievalError("Compressed source responses are not accepted.")
        content_type = headers.get("content-type", "")
        media_type = content_type.split(";", 1)[0].strip().lower()
        if media_type not in {"text/html", "application/xhtml+xml", "text/plain", "application/json"}:
            raise SourceRetrievalError("Source returned an unsupported content type.")
        title, excerpt = self._extract(content_type, body)
        return {
            "url": url,
            "domain": host,
            "title": title,
            "content_type": media_type,
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "excerpt": _select_excerpt(excerpt, self.max_excerpt_chars),
        }

    def retrieve_many(self, urls: list[str]) -> list[dict[str, Any]]:
        if not isinstance(urls, list) or not urls:
            raise SourceRetrievalError("At least one source URL is required.")
        if len(urls) > self.max_sources:
            raise SourceRetrievalError("Source count exceeds the configured limit.")
        if any(not isinstance(url, str) for url in urls):
            raise SourceRetrievalError("Every source reference must be a URL string.")
        if len(set(urls)) != len(urls):
            raise SourceRetrievalError("Duplicate source URLs are not accepted.")
        # All sources are required: partial retrieval must never be represented as complete.
        return [self.retrieve(url) for url in urls]


class SourceEvidenceChecker:
    """Retrieve source material; the independent reviewer judges claim support."""

    def __init__(self, retriever: TrustedSourceRetriever) -> None:
        self.retriever = retriever

    def __call__(
        self,
        candidate: Any,
        criterion: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        urls = context.get("source_refs")
        documents = self.retriever.retrieve_many(urls)
        bundle = [
            {"url": item["url"], "sha256": item["sha256"]}
            for item in documents
        ]
        digest = hashlib.sha256(
            json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return {
            "passed": True,
            "actual": {"source_count": len(documents), "sources": documents},
            "expected": criterion["target"],
            "evidence_ref": "source-bundle://sha256/" + digest,
            "details": (
                "Retrieved allowlisted source content with SHA-256 provenance. "
                "The independent reviewer must assess relevance and whether the source supports the candidate's claims."
            ),
        }


def source_retriever_from_env() -> TrustedSourceRetriever | None:
    raw_domains = os.getenv("UNEXPECTED_SOURCE_ALLOWED_DOMAINS", "")
    domains = [item.strip() for item in raw_domains.split(",") if item.strip()]
    if not domains:
        return None
    try:
        timeout = float(os.getenv("UNEXPECTED_SOURCE_TIMEOUT_SECONDS", "8"))
        max_bytes = int(os.getenv("UNEXPECTED_SOURCE_MAX_BYTES", "262144"))
        max_sources = int(os.getenv("UNEXPECTED_SOURCE_MAX_COUNT", "3"))
        return TrustedSourceRetriever(
            domains,
            timeout_seconds=timeout,
            max_bytes=max_bytes,
            max_sources=max_sources,
        )
    except (ValueError, TypeError):
        raise SourceRetrievalError("Source retrieval configuration is invalid.") from None
