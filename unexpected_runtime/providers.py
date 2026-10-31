from __future__ import annotations
import json, os, urllib.error, urllib.request
from urllib.parse import urlsplit
from typing import Protocol

class ProviderError(RuntimeError): pass
class Provider(Protocol):
    name: str
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str: ...

class DeterministicMockProvider:
    name = "deterministic-mock"
    configured = True
    def __init__(self): self.calls = 0; self.requests = []
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str:
        self.calls += 1
        self.requests.append({"system_prompt":system_prompt,"user_prompt":user_prompt,"agent_id":agent_id,"task_id":task_id})
        return f"MOCK_OK agent={agent_id} task={task_id}. This deterministic response verifies runtime plumbing only."

class OpenAICompatibleProvider:
    name = "openai-compatible"
    def __init__(self, base_url: str, model: str, api_key: str, default_timeout: float = 30.0):
        if not base_url or not model or not api_key: raise ProviderError("OpenAI-compatible provider requires URL, model and key in the host environment.")
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/chat/completions"): self.base_url += "/chat/completions"
        self.model, self._api_key, self.default_timeout = model, api_key, float(default_timeout)
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str:
        body = {"model":self.model,"messages":[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],"metadata":{"agent_id":agent_id,"task_id":task_id}}
        req = urllib.request.Request(self.base_url, data=json.dumps(body).encode(), headers={"Content-Type":"application/json","Authorization":"Bearer "+self._api_key}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=min(timeout,self.default_timeout)) as resp: data=json.loads(resp.read().decode())
        except Exception as exc: raise ProviderError(f"Provider request failed ({type(exc).__name__}); inspect host diagnostics without secrets.") from None
        try: return str(data["choices"][0]["message"]["content"])
        except Exception: raise ProviderError("Provider returned an unexpected response schema.") from None

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None

class AIStudioGatewayProvider:
    """Use the authenticated AI Studio gateway; provider keys stay there."""
    name = "unexpected-ai-studio-gateway"
    configured = False
    MODES = {"openai","claude","both"}
    def __init__(self, endpoint: str, token: str, *, mode: str = "openai", default_timeout: float = 200.0):
        p = urlsplit(str(endpoint or "").strip())
        if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ProviderError("AI Studio gateway URL must be HTTPS without embedded credentials, query or fragment.")
        path = p.path.rstrip("/") or "/orchestrate"
        if path == "/": path = "/orchestrate"
        self.endpoint = p._replace(path=path).geturl()
        self._token = str(token or "").strip()
        self.mode = str(mode or "openai").strip().lower()
        if self.mode not in self.MODES: raise ProviderError("Gateway mode must be openai, claude or both.")
        self.default_timeout = float(default_timeout)
        if self.default_timeout <= 0: raise ProviderError("Gateway timeout must be positive.")
        self.configured = bool(self._token)
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str:
        if not self._token: raise ProviderError("AI Studio gateway token is not configured in the runtime host.")
        task = f"uneXpected runtime agent: {agent_id}; task: {task_id}\n\nSYSTEM:\n{system_prompt}\n\nTASK AND CONTEXT:\n{user_prompt}"
        if len(task.encode("utf-16-le")) // 2 > 15000: raise ProviderError("Gateway task exceeds the 15,000 UTF-16-code-unit limit.")
        req = urllib.request.Request(self.endpoint, data=json.dumps({"task":task,"mode":self.mode},ensure_ascii=False).encode(),
            headers={"Content-Type":"application/json","Accept":"application/json","Authorization":"Bearer "+self._token},method="POST")
        try:
            opener=urllib.request.build_opener(_NoRedirect())
            with opener.open(req,timeout=min(max(float(timeout),0.1),self.default_timeout)) as resp: raw=resp.read(1_000_001)
            if len(raw)>1_000_000: raise ProviderError("Gateway response exceeded 1 MB.")
            data=json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc: raise ProviderError(f"AI Studio gateway rejected the request (HTTP {exc.code}).") from None
        except ProviderError: raise
        except Exception as exc: raise ProviderError(f"AI Studio gateway request failed ({type(exc).__name__}); check host diagnostics.") from None
        if not isinstance(data,dict) or data.get("ok") is not True or not isinstance(data.get("results"),dict):
            raise ProviderError("Gateway did not return a successful provider result.")
        candidates={"openai":("openai","synthesis"),"claude":("anthropic","synthesis"),"both":("synthesis","openai","anthropic")}[self.mode]
        for key in candidates:
            item=data["results"].get(key)
            if isinstance(item,dict) and isinstance(item.get("text"),str) and item["text"].strip() and "LIVE" in str(item.get("status","")).upper():
                return f"[Live AI result: {item.get('label') or key}; model={item.get('model') or 'provider model'}]\n{item['text'].strip()}"
        raise ProviderError("Gateway returned no live provider response; simulated or failed output was rejected.")

def provider_from_env():
    mode=os.getenv("UNEXPECTED_PROVIDER","mock").strip().lower()
    if mode=="mock": return DeterministicMockProvider()
    if mode in ("openai_compatible","openai-compatible"):
        return OpenAICompatibleProvider(os.getenv("UNEXPECTED_BASE_URL",""),os.getenv("UNEXPECTED_MODEL",""),os.getenv("UNEXPECTED_API_KEY",""),float(os.getenv("UNEXPECTED_DEFAULT_TIMEOUT_SECONDS","30")))
    if mode in ("ai_studio_gateway","unexpected_gateway","unexpected-ai-studio"):
        return AIStudioGatewayProvider(os.getenv("UNEXPECTED_GATEWAY_URL","https://unexpected-ai-studio.onrender.com/orchestrate"),os.getenv("UNEXPECTED_GATEWAY_TOKEN",""),mode=os.getenv("UNEXPECTED_GATEWAY_MODE","openai"),default_timeout=float(os.getenv("UNEXPECTED_GATEWAY_TIMEOUT_SECONDS","200")))
    raise ProviderError(f"Unsupported UNEXPECTED_PROVIDER mode: {mode}")
