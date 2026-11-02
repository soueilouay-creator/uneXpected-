import unittest
from unittest.mock import patch

from unexpected_runtime.source_retrieval import (
    SourceEvidenceChecker,
    _read_response_bounded,
    SourceRetrievalError,
    TrustedSourceRetriever,
    source_retriever_from_env,
)


class TrustedSourceRetrieverTests(unittest.TestCase):
    def _retriever(self, response=None, allowed_domains=("docs.python.org",), addresses=None):
        calls = []
        response = response or (
            200,
            {"content-type": "text/html; charset=utf-8", "content-encoding": "identity"},
            b"<html><head><title>Python unittest</title></head><body>"
            b"<h1>Test discovery</h1><p>unittest supports test discovery.</p>"
            b"<script>do not include secret()</script></body></html>",
        )

        def transport(host, address, request_target, timeout_seconds, max_bytes):
            calls.append((host, address, request_target, timeout_seconds, max_bytes))
            return response

        retriever = TrustedSourceRetriever(
            allowed_domains=allowed_domains,
            resolver=lambda host, port: addresses or ["93.184.216.34"],
            transport=transport,
        )
        return retriever, calls

    def test_retrieves_allowlisted_https_and_returns_bounded_provenance(self):
        retriever, calls = self._retriever()

        document = retriever.retrieve("https://docs.python.org/3/library/unittest.html")

        self.assertEqual(document["domain"], "docs.python.org")
        self.assertEqual(document["title"], "Python unittest")
        self.assertIn("unittest supports test discovery", document["excerpt"])
        self.assertNotIn("do not include secret", document["excerpt"])
        self.assertEqual(len(document["sha256"]), 64)
        self.assertEqual(calls[0][1], "93.184.216.34")
        self.assertEqual(calls[0][2], "/3/library/unittest.html")
        self.assertEqual(document["content_type"], "text/html")
        self.assertGreater(document["bytes"], 0)

    def test_rejects_unsafe_or_untrusted_urls_before_network_access(self):
        retriever, calls = self._retriever()
        urls = [
            "http://docs.python.org/3/library/unittest.html",
            "https://user:pass@docs.python.org/3/library/unittest.html",
            "https://docs.python.org:444/3/library/unittest.html",
            "https://docs.python.org/3/library/unittest.html#fragment",
            "https://example.com/document",
            "https://127.0.0.1/document",
            "https://localhost/document",
        ]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(SourceRetrievalError):
                retriever.retrieve(url)
        self.assertEqual(calls, [])

    def test_rejects_private_or_mixed_public_private_dns_answers(self):
        for addresses in (["127.0.0.1"], ["93.184.216.34", "10.0.0.8"], ["::1"]):
            retriever, calls = self._retriever(addresses=addresses)
            with self.subTest(addresses=addresses), self.assertRaises(SourceRetrievalError):
                retriever.retrieve("https://docs.python.org/document")
            self.assertEqual(calls, [])

    def test_redirects_unsupported_types_and_content_encodings_fail_closed(self):
        responses = [
            (302, {"location": "https://evil.example/collect"}, b""),
            (200, {"content-type": "application/octet-stream"}, b"binary"),
            (200, {"content-type": "text/plain", "content-encoding": "gzip"}, b"compressed"),
        ]
        for response in responses:
            retriever, calls = self._retriever(response=response)
            with self.subTest(response=response), self.assertRaises(SourceRetrievalError):
                retriever.retrieve("https://docs.python.org/document")
            self.assertEqual(len(calls), 1)

    def test_oversized_and_empty_documents_are_rejected(self):
        retriever, _ = self._retriever(
            response=(200, {"content-type": "text/plain"}, b"x" * 20),
        )
        retriever.max_bytes = 10
        with self.assertRaises(SourceRetrievalError):
            retriever.retrieve("https://docs.python.org/document")

        retriever, _ = self._retriever(response=(200, {"content-type": "text/plain"}, b"   "))
        with self.assertRaises(SourceRetrievalError):
            retriever.retrieve("https://docs.python.org/document")

    def test_source_checker_requires_all_sources_and_returns_review_material(self):
        retriever, _ = self._retriever()
        checker = SourceEvidenceChecker(retriever)
        criterion = {
            "id": "SOURCE-01",
            "description": "Retrieve an official source for independent review",
            "kind": "source",
            "target": "An allowlisted official document is retrieved with provenance",
            "required": True,
        }

        result = checker("candidate", criterion, {
            "source_refs": ["https://docs.python.org/3/library/unittest.html"],
        })

        self.assertTrue(result["passed"])
        self.assertEqual(result["actual"]["source_count"], 1)
        self.assertIn("Python unittest", result["actual"]["sources"][0]["title"])
        self.assertTrue(result["evidence_ref"].startswith("source-bundle://sha256/"))
        self.assertIn("reviewer", result["details"].lower())

    def test_source_checker_fails_when_source_refs_are_missing_or_too_many(self):
        retriever, calls = self._retriever()
        checker = SourceEvidenceChecker(retriever)
        criterion = {"id": "SOURCE-01", "description": "Get source", "kind": "source",
                     "target": "One source", "required": True}
        with self.assertRaises(SourceRetrievalError):
            checker("candidate", criterion, {"source_refs": []})
        with self.assertRaises(SourceRetrievalError):
            checker("candidate", criterion, {"source_refs": ["https://docs.python.org/1"] * 6})
        self.assertEqual(calls, [])

    def test_long_source_excerpt_preserves_context_near_test_discovery(self):
        from unexpected_runtime.source_retrieval import _select_excerpt

        text = ("General documentation background. " * 200
                + "The script is a GUI tool for test discovery and execution. "
                + "More background material. " * 200
                + "Unittest supports simple test discovery. Test files must be importable from the project root. "
                + "Additional reference material. " * 200)

        excerpt = _select_excerpt(text, 1200)

        self.assertLessEqual(len(excerpt), 1200)
        self.assertIn("unittest supports simple test discovery", excerpt.lower())

    def test_response_body_uses_one_absolute_deadline_across_slow_chunks(self):
        class FakeSocket:
            def __init__(self): self.timeouts = []
            def settimeout(self, value): self.timeouts.append(value)
        class FakeConnection:
            def __init__(self): self.sock = FakeSocket()
        class SlowResponse:
            def __init__(self): self.calls = 0
            def read1(self, size):
                self.calls += 1
                return b"data"
        times = iter([0.0, 0.3, 0.6, 0.9, 1.2])
        connection, response = FakeConnection(), SlowResponse()
        captured_socket = connection.sock
        connection.sock = None  # HTTPConnection.getresponse() may clear this reference.
        with self.assertRaisesRegex(SourceRetrievalError, "overall deadline"):
            _read_response_bounded(captured_socket, response, deadline=1.0, max_bytes=1024,
                                   clock=lambda: next(times))
        self.assertEqual(response.calls, 4)
        self.assertEqual(len(captured_socket.timeouts), 4)
        self.assertGreater(captured_socket.timeouts[0], captured_socket.timeouts[-1])

    def test_fetch_retains_socket_for_body_reads_after_getresponse_clears_it(self):
        from unittest.mock import patch
        from unexpected_runtime import source_retrieval

        class FakeSocket:
            def __init__(self):
                self.timeouts = []
            def settimeout(self, value):
                self.timeouts.append(value)

        class FakeResponse:
            status = 200
            def __init__(self):
                self.chunks = [b"verified body", b""]
                self.closed = False
            def getheaders(self):
                return [("content-type", "text/plain")]
            def read1(self, size):
                return self.chunks.pop(0)
            def close(self):
                self.closed = True

        captured_socket = FakeSocket()
        response = FakeResponse()

        class FakeConnection:
            def __init__(self, host, address, timeout_seconds, *, deadline):
                self.sock = captured_socket
                self.closed = False
            def request(self, method, target, headers):
                return None
            def getresponse(self):
                self.sock = None
                return response
            def close(self):
                self.closed = True

        with patch.object(source_retrieval, "_PinnedHTTPSConnection", FakeConnection):
            status, headers, body = source_retrieval._fetch_pinned_https(
                "docs.python.org", "93.184.216.34", "/document", 1.0, 1024
            )

        self.assertEqual(status, 200)
        self.assertEqual(headers["content-type"], "text/plain")
        self.assertEqual(body, b"verified body")
        self.assertGreaterEqual(len(captured_socket.timeouts), 3)
        self.assertTrue(response.closed)

    def test_real_chunked_response_cannot_extend_absolute_deadline(self):
        import http.client
        import socket
        import threading
        import time
        from unexpected_runtime import source_retrieval

        client_sock, server_sock = socket.socketpair()
        deadline = time.monotonic() + 0.30
        deadline_socket_type = getattr(source_retrieval, "_DeadlineSocket", None)
        active_socket = deadline_socket_type(client_sock, deadline) if deadline_socket_type else client_sock
        response = http.client.HTTPResponse(active_socket, method="GET")

        def serve():
            try:
                server_sock.sendall(
                    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n"
                )
                for byte in b"0000000000000001\r\n":
                    time.sleep(0.06)
                    server_sock.sendall(bytes([byte]))
                server_sock.sendall(b"a\r\n0\r\n\r\n")
            except OSError:
                pass

        sender = threading.Thread(target=serve, daemon=True)
        sender.start()
        try:
            response.begin()
            started = time.monotonic()
            with self.assertRaisesRegex(SourceRetrievalError, "overall deadline"):
                _read_response_bounded(
                    active_socket, response,
                    deadline=deadline, max_bytes=1024,
                )
            self.assertLess(time.monotonic() - started, 0.55)
        finally:
            response.close()
            active_socket.close()
            server_sock.close()
            sender.join(timeout=1)

    def test_slow_response_headers_obey_absolute_deadline(self):
        import http.client
        import socket
        import threading
        import time
        from unexpected_runtime import source_retrieval

        client_sock, server_sock = socket.socketpair()
        deadline = time.monotonic() + 0.28
        active_socket = source_retrieval._DeadlineSocket(client_sock, deadline)

        def serve():
            try:
                for byte in b"HTTP/1.1 200 OK\\r\\nContent-Length: 0\\r\\n\\r\\n":
                    time.sleep(0.04)
                    server_sock.sendall(bytes([byte]))
            except OSError:
                pass

        sender = threading.Thread(target=serve, daemon=True)
        sender.start()
        response = http.client.HTTPResponse(active_socket, method="GET")
        try:
            started = time.monotonic()
            with self.assertRaises(source_retrieval._DeadlineExceeded):
                response.begin()
            self.assertLess(time.monotonic() - started, 0.55)
        finally:
            response.close()
            active_socket.close()
            server_sock.close()
            sender.join(timeout=1)

    def test_environment_factory_is_disabled_without_an_allowlist(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(source_retriever_from_env())

    def test_rejects_invalid_allowlist_configuration(self):
        with self.assertRaises(SourceRetrievalError):
            TrustedSourceRetriever(allowed_domains=["*.python.org"])
        with self.assertRaises(SourceRetrievalError):
            TrustedSourceRetriever(allowed_domains=["localhost"])


if __name__ == "__main__":
    unittest.main()
