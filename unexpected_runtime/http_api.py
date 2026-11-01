from __future__ import annotations
import hmac, json, os, threading, time, math, re, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit, unquote, quote
from . import __version__
from .coordinator import Coordinator

MAX_BODY_BYTES=64*1024
MAX_OBJECTIVE_CHARS=16000
RATE_LIMIT_PER_MINUTE=30
SOCKET_TIMEOUT_SECONDS=10
MAX_SOURCE_REF_CHARS=2048

class _RateLimiter:
    def __init__(self): self.lock=threading.Lock(); self.entries={}
    def allow(self, identity):
        now=time.monotonic()
        with self.lock:
            start,count=self.entries.get(identity,(now,0))
            if now-start>=60: start,count=now,0
            count+=1; self.entries[identity]=(start,count)
            if len(self.entries)>2000: self.entries={k:v for k,v in self.entries.items() if now-v[0]<60}
            return count<=RATE_LIMIT_PER_MINUTE

def create_server(*, coordinator=None, api_token=None, host="127.0.0.1", port=0):
    active = coordinator or Coordinator()
    token = (os.getenv("UNEXPECTED_RUNTIME_API_TOKEN", "") if api_token is None else str(api_token or "")).strip()
    limiter = _RateLimiter()
    uploaded_files: dict[str, dict[str, Any]] = {}
    generated_artifacts: dict[str, dict[str, Any]] = {}
    file_lock = threading.RLock()
    file_id_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
    xlsx_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    max_excel_bytes = 20 * 1024 * 1024
    excel_ttl_seconds = 1800

    def active_provider():
        return getattr(active, "provider", None)

    def is_excel_gateway():
        provider = active_provider()
        return bool(
            getattr(provider, "configured", False)
            and getattr(provider, "supports_excel_files", False)
            and callable(getattr(provider, "upload_workbook", None))
            and callable(getattr(provider, "download_artifact", None))
        )

    def valid_file_id(value):
        return isinstance(value, str) and bool(file_id_pattern.fullmatch(value))

    def prune_files():
        now = time.time()
        with file_lock:
            for registry in (uploaded_files, generated_artifacts):
                for key in [key for key, value in registry.items() if value.get("expires_at", 0) <= now]:
                    registry.pop(key, None)

    def raw_body(handler, max_bytes):
        raw_length = handler.headers.get("Content-Length")
        if raw_length is None:
            handler.send_json(411, {"error": "Content-Length is required."})
            return None
        try:
            length = int(raw_length)
        except ValueError:
            handler.send_json(400, {"error": "Invalid Content-Length."})
            return None
        if length < 4:
            handler.send_json(400, {"error": "XLSX body is empty or too small."})
            return None
        if length > max_bytes:
            handler.send_json(413, {"error": "Excel upload exceeds the 20 MiB limit."})
            return None
        try:
            data = handler.rfile.read(length)
        except OSError:
            handler.send_json(400, {"error": "Could not read the Excel upload body."})
            return None
        if len(data) != length:
            handler.send_json(400, {"error": "Excel upload body was truncated."})
            return None
        if data[:4] != bytes((0x50, 0x4b, 0x03, 0x04)):
            handler.send_json(400, {"error": "Upload is not an XLSX ZIP package."})
            return None
        return data

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(SOCKET_TIMEOUT_SECONDS)
            super().setup()

        server_version = "uneXpectedRuntime/7"
        sys_version = ""

        def log_message(self, fmt, *args):
            return

        def send_json(self, code, obj):
            data = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(data)

        def authorize(self):
            if len(token) < 32 or not token.isascii():
                self.send_json(503, {"error": "Runtime API is locked."})
                return False
            supplied = self.headers.get("Authorization", "")
            try:
                supplied_bytes = supplied.encode("ascii")
                expected_bytes = ("Bearer " + token).encode("ascii")
            except UnicodeEncodeError:
                self.send_json(401, {"error": "Unauthorized."})
                return False
            if not hmac.compare_digest(supplied_bytes, expected_bytes):
                self.send_json(401, {"error": "Unauthorized."})
                return False
            return True

        def read_body(self):
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self.send_json(411, {"error": "Content-Length is required."})
                return None
            try:
                length = int(raw_length)
            except ValueError:
                self.send_json(400, {"error": "Invalid Content-Length."})
                return None
            if length < 0:
                self.send_json(400, {"error": "Invalid Content-Length."})
                return None
            if length > MAX_BODY_BYTES:
                self.send_json(413, {"error": "Request body too large."})
                return None
            try:
                obj = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_json(400, {"error": "Body must be valid UTF-8 JSON."})
                return None
            if not isinstance(obj, dict):
                self.send_json(400, {"error": "Body must be a JSON object."})
                return None
            return obj

        def excel_rate_limit(self):
            identity = self.client_address[0] if self.client_address else "unknown"
            if not limiter.allow(identity):
                self.send_json(429, {"error": "Request rate limit exceeded."})
                return False
            return True

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/health":
                provider = active_provider()
                return self.send_json(200, {
                    "ok": True,
                    "service": "uneXpected governed runtime",
                    "version": __version__,
                    "provider": getattr(provider, "name", type(provider).__name__ if provider else "unavailable"),
                    "provider_configured": bool(getattr(provider, "configured", True)),
                    "excel_gateway_configured": is_excel_gateway(),
                    "authentication_configured": len(token) >= 32,
                    "privileged_actions": "fail-closed"
                })
            if path == "/v1/status":
                if not self.authorize():
                    return
                status = active.status()
                return self.send_json(200, {
                    **{k: status.get(k) for k in (
                        "ecosystem_version", "registered_agents", "provider", "mode",
                        "max_workers", "max_retries", "approval_verifier"
                    )},
                    "excel_gateway_configured": is_excel_gateway(),
                    "excel_upload_limit_bytes": max_excel_bytes,
                    "excel_file_ttl_seconds": excel_ttl_seconds
                })

            match = re.fullmatch(r"/v1/excel/artifacts/([0-9a-fA-F-]{36})", path)
            if match:
                if not self.authorize():
                    return
                if not self.excel_rate_limit():
                    return
                artifact_id = match.group(1)
                prune_files()
                with file_lock:
                    record = generated_artifacts.get(artifact_id)
                if not record:
                    return self.send_json(410, {"error": "Excel artifact expired or is not attached to this runtime session."})
                provider = active_provider()
                if not is_excel_gateway():
                    return self.send_json(503, {"error": "Excel gateway is not configured."})
                try:
                    downloaded = provider.download_artifact(artifact_id, timeout=30.0)
                    data = downloaded.get("bytes") if isinstance(downloaded, dict) else None
                    file_name = record["file_name"]
                    if (not isinstance(data, bytes) or len(data) < 4 or len(data) > max_excel_bytes
                            or data[:4] != bytes((0x50, 0x4b, 0x03, 0x04))):
                        raise ValueError("Downloaded Excel artifact failed file validation.")
                    mime = xlsx_mime
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Content-Disposition", "attachment; filename=\"" + file_name + "\"")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception as exc:
                    return self.send_json(502, {"error": f"Excel artifact download failed ({type(exc).__name__})."})
            return self.send_json(404, {"error": "Not found."})

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == "/v1/excel/upload":
                if not self.authorize():
                    return
                if not self.excel_rate_limit():
                    return
                if not is_excel_gateway():
                    return self.send_json(503, {"error": "The configured provider does not support Excel file transfer."})
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type not in (xlsx_mime, "application/octet-stream"):
                    return self.send_json(415, {"error": "Use the XLSX or application/octet-stream content type."})
                data = raw_body(self, max_excel_bytes)
                if data is None:
                    return
                encoded_name = self.headers.get("X-File-Name", "workbook.xlsx")
                try:
                    file_name = unquote(encoded_name, errors="strict")
                except (UnicodeDecodeError, ValueError):
                    return self.send_json(400, {"error": "x-file-name must be URL-encoded UTF-8."})
                file_name = file_name.replace("\\\\", "/").split("/")[-1].strip()
                if (not file_name or not file_name.lower().endswith(".xlsx") or len(file_name) > 180
                        or any(ord(ch) < 32 for ch in file_name)):
                    return self.send_json(400, {"error": "Excel filename must be a safe .xlsx basename."})
                try:
                    record = active_provider().upload_workbook(data, file_name, timeout=30.0)
                    file_id = record.get("id") if isinstance(record, dict) else None
                    size = record.get("sizeBytes") if isinstance(record, dict) else None
                    expiry = record.get("expiresInSeconds") if isinstance(record, dict) else None
                    name = record.get("name") if isinstance(record, dict) else None
                    if (not valid_file_id(file_id) or size != len(data) or name != file_name
                            or isinstance(expiry, bool) or not isinstance(expiry, int) or not 1 <= expiry <= excel_ttl_seconds):
                        raise ValueError("Gateway returned invalid uploaded workbook metadata.")
                    with file_lock:
                        prune_files()
                        uploaded_files[file_id] = {
                            "file_name": file_name, "size_bytes": size,
                            "expires_at": time.time() + expiry
                        }
                    return self.send_json(201, {"file": {
                        "id": file_id, "name": file_name, "sizeBytes": size,
                        "expiresInSeconds": expiry
                    }})
                except Exception as exc:
                    return self.send_json(502, {"error": f"Excel upload failed ({type(exc).__name__})."})

            if path != "/v1/invoke":
                return self.send_json(404, {"error": "Not found."})
            if not self.authorize():
                return
            if not self.excel_rate_limit():
                return
            body = self.read_body()
            if body is None:
                return
            allowed = {"agent_id", "objective", "inputs", "deadline_seconds", "max_steps", "idempotency_key", "source_refs"}
            if set(body) - allowed:
                return self.send_json(400, {"error": "Unsupported fields; privileged actions are not exposed."})
            agent = body.get("agent_id")
            objective = body.get("objective")
            inputs = body.get("inputs", {})
            deadline = body.get("deadline_seconds", 195.0)
            steps = body.get("max_steps", 6)
            idem = body.get("idempotency_key")
            refs = body.get("source_refs", [])
            if not isinstance(agent, str) or not agent.strip() or not isinstance(objective, str) or not objective.strip():
                return self.send_json(400, {"error": "agent_id and objective are required."})
            if len(objective) > MAX_OBJECTIVE_CHARS:
                return self.send_json(413, {"error": "Objective too large."})
            if not isinstance(inputs, dict) or isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or isinstance(steps, bool) or not isinstance(steps, int):
                return self.send_json(400, {"error": "Invalid inputs, deadline or max_steps."})
            if not math.isfinite(float(deadline)) or not 0 < float(deadline) <= 600:
                return self.send_json(400, {"error": "deadline_seconds must be finite and between 0 and 600."})
            if not 1 <= steps <= 12:
                return self.send_json(400, {"error": "max_steps must be between 1 and 12."})
            if idem is not None and (not isinstance(idem, str) or len(idem) > 128):
                return self.send_json(400, {"error": "Invalid idempotency key."})
            if not isinstance(refs, list) or len(refs) > 32 or any(not isinstance(x, str) or not x or len(x) > MAX_SOURCE_REF_CHARS for x in refs):
                return self.send_json(400, {"error": "Invalid source_refs."})

            requested_ids = inputs.get("excel_file_ids", [])
            if requested_ids:
                if not is_excel_gateway():
                    return self.send_json(503, {"error": "The configured provider does not support attached Excel workbooks."})
                if not isinstance(requested_ids, list) or not 1 <= len(requested_ids) <= 8:
                    return self.send_json(400, {"error": "inputs.excel_file_ids must contain 1 to 8 uploaded workbook IDs."})
                if len(set(requested_ids)) != len(requested_ids) or any(not valid_file_id(value) for value in requested_ids):
                    return self.send_json(400, {"error": "Invalid or duplicate Excel attachment ID."})
                prune_files()
                with file_lock:
                    missing = [value for value in requested_ids if value not in uploaded_files]
                if missing:
                    return self.send_json(403, {"error": "Excel attachment was not uploaded to this runtime session or has expired."})

            try:
                result = active.invoke(
                    agent.strip(), objective, inputs, deadline_seconds=float(deadline),
                    max_steps=steps, idempotency_key=idem, source_refs=tuple(refs)
                ).to_dict()
                if result.get("status") != "completed":
                    return self.send_json(502, {"result": result})
                presented_artifacts = []
                for artifact in result.get("output_artifacts", []):
                    artifact_id = artifact.get("id") if isinstance(artifact, dict) else None
                    file_name = artifact.get("fileName") if isinstance(artifact, dict) else None
                    size = artifact.get("sizeBytes") if isinstance(artifact, dict) else None
                    expiry = artifact.get("expiresInSeconds") if isinstance(artifact, dict) else None
                    if (not valid_file_id(artifact_id) or not isinstance(file_name, str)
                            or not file_name.lower().endswith(".xlsx")
                            or isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= max_excel_bytes
                            or isinstance(expiry, bool) or not isinstance(expiry, int) or not 1 <= expiry <= excel_ttl_seconds):
                        return self.send_json(502, {"error": "Provider returned invalid Excel artifact metadata."})
                    download_path = "/v1/excel/artifacts/" + artifact_id
                    with file_lock:
                        generated_artifacts[artifact_id] = {
                            "file_name": file_name, "size_bytes": size,
                            "expires_at": time.time() + expiry
                        }
                    presented_artifacts.append({
                        "id": artifact_id, "file_name": file_name, "size_bytes": size,
                        "expires_in_seconds": expiry, "download_path": download_path
                    })
                result["output_artifacts"] = presented_artifacts
                result["artifacts"] = presented_artifacts
                return self.send_json(200, {"result": result})
            except Exception as exc:
                return self.send_json(400, {"error": f"Task rejected or failed ({type(exc).__name__})."})

    server = ThreadingHTTPServer((host, int(port)), Handler)
    server.daemon_threads = True
    server.allow_reuse_address = True
    server.coordinator = active
    server.owns_coordinator = coordinator is None
    return server

def main():
    server=create_server(host=os.getenv("UNEXPECTED_RUNTIME_BIND_HOST","0.0.0.0"),port=int(os.getenv("PORT",os.getenv("UNEXPECTED_RUNTIME_PORT","10000"))))
    try: server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt: return 0
    finally:
        server.shutdown(); server.server_close()
        if server.owns_coordinator: server.coordinator.close()
    return 0

if __name__=="__main__": raise SystemExit(main())
