from __future__ import annotations
import hmac, json, os, threading, time, math
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit
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
    active=coordinator or Coordinator()
    token=(os.getenv("UNEXPECTED_RUNTIME_API_TOKEN","") if api_token is None else str(api_token or "")).strip()
    limiter=_RateLimiter()
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(SOCKET_TIMEOUT_SECONDS)
            super().setup()
        server_version="uneXpectedRuntime/7"; sys_version=""
        def log_message(self, fmt, *args): return
        def send_json(self, code, obj):
            data=json.dumps(obj,ensure_ascii=False).encode()
            self.send_response(code); self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(data))); self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff"); self.send_header("Referrer-Policy","no-referrer")
            self.end_headers(); self.wfile.write(data)
        def authorize(self):
            if len(token)<32 or not token.isascii():
                self.send_json(503,{"error":"Runtime API is locked."}); return False
            supplied = self.headers.get("Authorization", "")
            try:
                supplied_bytes = supplied.encode("ascii")
                expected_bytes = ("Bearer " + token).encode("ascii")
            except UnicodeEncodeError:
                self.send_json(401,{"error":"Unauthorized."}); return False
            if not hmac.compare_digest(supplied_bytes, expected_bytes):
                self.send_json(401,{"error":"Unauthorized."}); return False
            return True
        def read_body(self):
            raw_length=self.headers.get("Content-Length")
            if raw_length is None:
                self.send_json(411,{"error":"Content-Length is required."}); return None
            try: length=int(raw_length)
            except ValueError: self.send_json(400,{"error":"Invalid Content-Length."}); return None
            if length<0: self.send_json(400,{"error":"Invalid Content-Length."}); return None
            if length>MAX_BODY_BYTES: self.send_json(413,{"error":"Request body too large."}); return None
            try: obj=json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError,json.JSONDecodeError): self.send_json(400,{"error":"Body must be valid UTF-8 JSON."}); return None
            if not isinstance(obj,dict): self.send_json(400,{"error":"Body must be a JSON object."}); return None
            return obj
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=="/health":
                provider=getattr(active,"provider",None)
                return self.send_json(200,{"ok":True,"service":"uneXpected governed runtime","version":__version__,
                    "provider":getattr(provider,"name",type(provider).__name__ if provider else "unavailable"),
                    "provider_configured":bool(getattr(provider,"configured",True)),
                    "authentication_configured":len(token)>=32,"privileged_actions":"fail-closed"})
            if path=="/v1/status":
                if not self.authorize(): return
                status=active.status()
                return self.send_json(200,{k:status.get(k) for k in ("ecosystem_version","registered_agents","provider","mode","max_workers","max_retries","approval_verifier")})
            return self.send_json(404,{"error":"Not found."})
        def do_POST(self):
            route=urlsplit(self.path).path
            if route not in {"/v1/invoke", "/v1/lifecycle"}: return self.send_json(404,{"error":"Not found."})
            is_lifecycle=route=="/v1/lifecycle"
            if not self.authorize(): return
            identity=self.client_address[0] if self.client_address else "unknown"
            if not limiter.allow(identity): return self.send_json(429,{"error":"Request rate limit exceeded."})
            body=self.read_body()
            if body is None: return
            allowed=({"agent_id","objective","inputs","deadline_seconds","max_corrections"}
                     if is_lifecycle else
                     {"agent_id","objective","inputs","deadline_seconds","max_steps","idempotency_key","source_refs"})
            if set(body)-allowed: return self.send_json(400,{"error":"Unsupported fields; privileged actions are not exposed."})
            agent=body.get("agent_id"); objective=body.get("objective"); inputs=body.get("inputs",{})
            deadline=body.get("deadline_seconds",60.0 if is_lifecycle else 195.0)
            steps=body.get("max_steps",6)
            idem=body.get("idempotency_key"); refs=body.get("source_refs",[])
            corrections=body.get("max_corrections",1)
            if not isinstance(agent,str) or not agent.strip() or not isinstance(objective,str) or not objective.strip():
                return self.send_json(400,{"error":"agent_id and objective are required."})
            if len(objective)>MAX_OBJECTIVE_CHARS: return self.send_json(413,{"error":"Objective too large."})
            if (not isinstance(inputs,dict) or isinstance(deadline,bool) or not isinstance(deadline,(int,float))
                    or (not is_lifecycle and (isinstance(steps,bool) or not isinstance(steps,int)))
                    or (is_lifecycle and (isinstance(corrections,bool) or not isinstance(corrections,int)))):
                return self.send_json(400,{"error":"Invalid inputs, deadline or workflow limits."})
            if not math.isfinite(float(deadline)) or not 0 < float(deadline) <= 600:
                return self.send_json(400,{"error":"deadline_seconds must be finite and between 0 and 600."})
            if is_lifecycle:
                if not 0 <= corrections <= 2:
                    return self.send_json(400,{"error":"max_corrections must be between 0 and 2 for the HTTP workflow endpoint."})
            else:
                if not 1 <= steps <= 12:
                    return self.send_json(400,{"error":"max_steps must be between 1 and 12."})
                if idem is not None and (not isinstance(idem,str) or len(idem)>128): return self.send_json(400,{"error":"Invalid idempotency key."})
                if not isinstance(refs,list) or len(refs)>32 or any(not isinstance(x,str) or not x or len(x)>MAX_SOURCE_REF_CHARS for x in refs): return self.send_json(400,{"error":"Invalid source_refs."})
            try:
                if is_lifecycle:
                    result=active.run_lifecycle(agent.strip(),objective,inputs,
                                                deadline_seconds=float(deadline),
                                                max_corrections=corrections).to_dict()
                    success=result.get("status")=="delivered" and result.get("delivered") is True
                else:
                    result=active.invoke(agent.strip(),objective,inputs,deadline_seconds=float(deadline),
                                         max_steps=steps,idempotency_key=idem,source_refs=tuple(refs)).to_dict()
                    success=result.get("status")=="completed"
                return self.send_json(200 if success else 502,{"result":result})
            except Exception as exc: return self.send_json(400,{"error":f"Task rejected or failed ({type(exc).__name__})."})
    server=ThreadingHTTPServer((host,int(port)),Handler)
    server.daemon_threads=True; server.allow_reuse_address=True; server.coordinator=active; server.owns_coordinator=coordinator is None
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
