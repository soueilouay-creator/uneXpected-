from __future__ import annotations
import json, os, re, urllib.error, urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import quote, urlsplit, urlunsplit

class ProviderError(RuntimeError): pass

@dataclass(frozen=True)
class ProviderResponse:
    text: str
    excel_artifacts: tuple[dict[str, Any], ...] = ()

class Provider(Protocol):
    name: str
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str: ...

class DeterministicMockProvider:
    name = "deterministic-mock"
    configured = True
    retry_safe = True
    def __init__(self): self.calls = 0; self.requests = []
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str:
        self.calls += 1
        self.requests.append({"system_prompt":system_prompt,"user_prompt":user_prompt,"agent_id":agent_id,"task_id":task_id})
        return f"MOCK_OK agent={agent_id} task={task_id}. This deterministic response verifies runtime plumbing only."

class OpenAICompatibleProvider:
    name = "openai-compatible"
    def __init__(self, base_url: str, model: str, api_key: str, default_timeout: float = 30.0):
        if not isinstance(base_url, str) or not base_url.strip() or not model or not api_key:
            raise ProviderError("OpenAI-compatible provider requires URL, model and key in the host environment.")
        try:
            parsed = urlsplit(base_url.strip())
            if (parsed.scheme.lower() != "https" or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment):
                raise ValueError("unsafe provider URL")
        except ValueError:
            raise ProviderError("OpenAI-compatible base URL must use HTTPS without embedded credentials, query or fragment.") from None
        path = parsed.path.rstrip("/")
        if not path.endswith("/chat/completions"):
            path += "/chat/completions"
        self.base_url = parsed._replace(path=path).geturl()
        self.model, self._api_key, self.default_timeout = model, api_key, float(default_timeout)
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str:
        body = {"model":self.model,"messages":[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],"metadata":{"agent_id":agent_id,"task_id":task_id}}
        req = urllib.request.Request(self.base_url, data=json.dumps(body).encode(), headers={"Content-Type":"application/json","Authorization":"Bearer "+self._api_key}, method="POST")
        try:
            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=min(timeout,self.default_timeout)) as resp: data=json.loads(resp.read().decode())
        except Exception as exc: raise ProviderError(f"Provider request failed ({type(exc).__name__}); inspect host diagnostics without secrets.") from None
        try: return str(data["choices"][0]["message"]["content"])
        except Exception: raise ProviderError("Provider returned an unexpected response schema.") from None

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

class AIStudioGatewayProvider:
    """Authenticated bridge to the Node AI Studio gateway; provider secrets stay there."""
    name = "unexpected-ai-studio-gateway"
    configured = False
    supports_excel_files = True
    MODES = {"openai", "claude", "both"}
    MAX_EXCEL_BYTES = 20 * 1024 * 1024
    FILE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
    XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def __init__(self, endpoint: str, token: str, *, mode: str = "openai", default_timeout: float = 200.0):
        p = urlsplit(str(endpoint or "").strip())
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ProviderError("AI Studio gateway URL must be HTTPS without embedded credentials, query or fragment.")
        path = p.path.rstrip("/") or "/orchestrate"
        if path == "/":
            path = "/orchestrate"
        self.endpoint = p._replace(path=path).geturl()
        self.origin = urlunsplit((p.scheme, p.netloc, "", "", ""))
        self._token = str(token or "").strip()
        self.mode = str(mode or "openai").strip().lower()
        if self.mode not in self.MODES:
            raise ProviderError("Gateway mode must be openai, claude or both.")
        self.default_timeout = float(default_timeout)
        if self.default_timeout <= 0:
            raise ProviderError("Gateway timeout must be positive.")
        self.configured = bool(self._token)

    @classmethod
    def _validate_file_ids(cls, file_ids) -> list[str]:
        if file_ids is None:
            return []
        if not isinstance(file_ids, (list, tuple)) or len(file_ids) > 8:
            raise ProviderError("Attach no more than 8 uploaded Excel file IDs.")
        values = []
        for file_id in file_ids:
            if not isinstance(file_id, str) or not cls.FILE_ID.fullmatch(file_id):
                raise ProviderError("An Excel attachment ID is invalid.")
            if file_id in values:
                raise ProviderError("Duplicate Excel attachment IDs are not accepted.")
            values.append(file_id)
        return values

    @classmethod
    def _validate_artifacts(cls, raw) -> tuple[dict[str, Any], ...]:
        if raw is None:
            return ()
        if not isinstance(raw, list) or len(raw) > 8:
            raise ProviderError("Gateway returned an invalid Excel artifact collection.")
        artifacts = []
        for item in raw:
            if not isinstance(item, dict):
                raise ProviderError("Gateway returned invalid Excel artifact metadata.")
            file_id = item.get("id")
            filename = item.get("fileName")
            size = item.get("sizeBytes")
            expiry = item.get("expiresInSeconds")
            expected_path = "/excel/download/" + str(file_id)
            if (
                not isinstance(file_id, str) or not cls.FILE_ID.fullmatch(file_id)
                or not isinstance(filename, str) or not filename.lower().endswith(".xlsx")
                or len(filename) > 180 or any(ord(ch) < 32 or ch in ("/", "\\\\") for ch in filename)
                or isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= cls.MAX_EXCEL_BYTES
                or isinstance(expiry, bool) or not isinstance(expiry, int) or not 1 <= expiry <= 1800
                or item.get("downloadPath") != expected_path
            ):
                raise ProviderError("Gateway returned invalid Excel artifact details.")
            artifacts.append({
                "id": file_id, "fileName": filename, "sizeBytes": size,
                "expiresInSeconds": expiry, "downloadPath": expected_path
            })
        return tuple(artifacts)

    def _open_json(self, request, timeout: float, label: str) -> dict[str, Any]:
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=min(max(float(timeout), 0.1), self.default_timeout)) as response:
                raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise ProviderError(f"{label} response exceeded 1 MB.")
            data = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"{label} rejected the request (HTTP {exc.code}).") from None
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"{label} failed ({type(exc).__name__}); check host diagnostics.") from None
        if not isinstance(data, dict):
            raise ProviderError(f"{label} returned an invalid response.")
        return data

    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str,
                 timeout: float, excel_file_ids=()) -> ProviderResponse:
        if not self._token:
            raise ProviderError("AI Studio gateway token is not configured in the runtime host.")
        file_ids = self._validate_file_ids(excel_file_ids)
        task = (
            f"uneXpected runtime agent: {agent_id}; task: {task_id}"
            f"\n\nSYSTEM:\n{system_prompt}\n\nTASK AND CONTEXT:\n{user_prompt}"
        )
        if len(task.encode("utf-16-le")) // 2 > 15000:
            raise ProviderError("Gateway task exceeds the 15,000 UTF-16-code-unit limit.")
        payload = {"task": task, "mode": self.mode}
        if file_ids:
            payload["excelFiles"] = file_ids
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer " + self._token
            },
            method="POST"
        )
        data = self._open_json(request, timeout, "AI Studio gateway")
        if data.get("ok") is not True or not isinstance(data.get("results"), dict):
            raise ProviderError("Gateway did not return a successful provider result.")
        artifacts = self._validate_artifacts(data.get("excelArtifacts"))
        candidates = {
            "openai": ("openai", "synthesis"),
            "claude": ("anthropic", "synthesis"),
            "both": ("synthesis", "openai", "anthropic")
        }[self.mode]
        for key in candidates:
            item = data["results"].get(key)
            status = str(item.get("status", "")).strip().upper() if isinstance(item, dict) else ""
            is_live = status.startswith("LIVE") and not any(
                marker in status for marker in ("MOCK", "FALLBACK", "DELIVERED", "NOT LIVE")
            )
            if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip() and is_live:
                result_text = (
                    f"[Live AI result: {item.get('label') or key}; "
                    f"model={item.get('model') or 'provider model'}]\n{item['text'].strip()}"
                )
                return ProviderResponse(text=result_text, excel_artifacts=artifacts)
        raise ProviderError("Gateway returned no live provider response; simulated or failed output was rejected.")

    def upload_workbook(self, data: bytes, file_name: str, timeout: float = 30.0) -> dict[str, Any]:
        if not self._token:
            raise ProviderError("AI Studio gateway token is not configured in the runtime host.")
        if not isinstance(data, (bytes, bytearray)) or not 4 <= len(data) <= self.MAX_EXCEL_BYTES:
            raise ProviderError("Excel upload must be between 4 bytes and 20 MiB.")
        if bytes(data[:4]) != b"PK\\x03\\x04":
            raise ProviderError("Excel upload is not an XLSX ZIP package.")
        if not isinstance(file_name, str) or not file_name.lower().endswith(".xlsx"):
            raise ProviderError("Only .xlsx workbook uploads are supported.")
        safe_name = file_name.replace("\\\\", "/").split("/")[-1].strip()
        if not safe_name or len(safe_name) > 180 or any(ord(ch) < 32 for ch in safe_name):
            raise ProviderError("Excel upload filename is invalid.")
        request = urllib.request.Request(
            self.origin + "/excel/upload",
            data=bytes(data),
            headers={
                "Content-Type": self.XLSX_MIME,
                "Accept": "application/json",
                "Authorization": "Bearer " + self._token,
                "X-File-Name": quote(safe_name, safe="")
            },
            method="POST"
        )
        response = self._open_json(request, timeout, "AI Studio Excel upload")
        file_info = response.get("file")
        if response.get("ok") is not True or not isinstance(file_info, dict):
            raise ProviderError("AI Studio gateway returned an invalid Excel upload response.")
        file_id = file_info.get("id")
        size = file_info.get("sizeBytes")
        expiry = file_info.get("expiresInSeconds")
        name = file_info.get("name") or file_info.get("fileName") or safe_name
        if (
            not isinstance(file_id, str) or not self.FILE_ID.fullmatch(file_id)
            or isinstance(size, bool) or size != len(data)
            or isinstance(expiry, bool) or not isinstance(expiry, int) or not 1 <= expiry <= 1800
            or name != safe_name
        ):
            raise ProviderError("AI Studio gateway returned invalid uploaded workbook metadata.")
        return {
            "id": file_id, "name": safe_name, "sizeBytes": size,
            "expiresInSeconds": expiry
        }

    def download_artifact(self, artifact_id: str, timeout: float = 30.0) -> dict[str, Any]:
        if not self._token:
            raise ProviderError("AI Studio gateway token is not configured in the runtime host.")
        if not isinstance(artifact_id, str) or not self.FILE_ID.fullmatch(artifact_id):
            raise ProviderError("Excel artifact ID is invalid.")
        request = urllib.request.Request(
            self.origin + "/excel/download/" + artifact_id,
            headers={
                "Accept": self.XLSX_MIME,
                "Authorization": "Bearer " + self._token
            },
            method="GET"
        )
        try:
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=min(max(float(timeout), 0.1), self.default_timeout)) as response:
                raw = response.read(self.MAX_EXCEL_BYTES + 1)
                content_type = str(response.headers.get("Content-Type", ""))
                disposition = str(response.headers.get("Content-Disposition", ""))
            if len(raw) > self.MAX_EXCEL_BYTES:
                raise ProviderError("Excel artifact exceeded the 20 MiB download limit.")
            if len(raw) < 4 or raw[:4] != b"PK\\x03\\x04" or "spreadsheetml" not in content_type.lower():
                raise ProviderError("AI Studio returned an invalid XLSX artifact.")
            filename_match = re.search(r'filename="?([^";]+)', disposition, re.I)
            filename = filename_match.group(1) if filename_match else "workbook.xlsx"
            if not filename.lower().endswith(".xlsx") or any(ch in filename for ch in ("/", "\\\\", "\r", "\n")):
                filename = "workbook.xlsx"
            return {"bytes": raw, "fileName": filename, "sizeBytes": len(raw)}
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"AI Studio Excel artifact unavailable (HTTP {exc.code}).") from None
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"AI Studio Excel artifact download failed ({type(exc).__name__}).") from None

def provider_from_env():
    mode=os.getenv("UNEXPECTED_PROVIDER","mock").strip().lower()
    if mode=="mock": return DeterministicMockProvider()
    if mode in ("openai_compatible","openai-compatible"):
        return OpenAICompatibleProvider(os.getenv("UNEXPECTED_BASE_URL",""),os.getenv("UNEXPECTED_MODEL",""),os.getenv("UNEXPECTED_API_KEY",""),float(os.getenv("UNEXPECTED_DEFAULT_TIMEOUT_SECONDS","30")))
    if mode in ("ai_studio_gateway","unexpected_gateway","unexpected-ai-studio"):
        return AIStudioGatewayProvider(os.getenv("UNEXPECTED_GATEWAY_URL","https://unexpected-ai-studio.onrender.com/orchestrate"),os.getenv("UNEXPECTED_GATEWAY_TOKEN",""),mode=os.getenv("UNEXPECTED_GATEWAY_MODE","openai"),default_timeout=float(os.getenv("UNEXPECTED_GATEWAY_TIMEOUT_SECONDS","200")))
    raise ProviderError(f"Unsupported UNEXPECTED_PROVIDER mode: {mode}")
