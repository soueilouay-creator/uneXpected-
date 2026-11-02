from __future__ import annotations
import json, os, urllib.error, urllib.request
from urllib.parse import urlsplit
from typing import Protocol

class ProviderError(RuntimeError): pass


class ProviderText(str):
    """Plain model text with separate, non-prompt provider metadata."""

    def __new__(cls, value: str, provider_metadata: dict[str, str]):
        instance = super().__new__(cls, value)
        instance.provider_metadata = dict(provider_metadata)
        return instance


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
    """Use the authenticated AI Studio gateway; provider keys stay there."""
    name = "unexpected-ai-studio-gateway"
    configured = False
    MODES = {"openai","claude","both"}
    MAX_TASK_CODE_UNITS = 15000
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
    @staticmethod
    def _task_prefix(system_prompt: str, agent_id: str, task_id: str) -> str:
        return f"uneXpected runtime agent: {agent_id}; task: {task_id}\n\nSYSTEM:\n{system_prompt}\n\nTASK AND CONTEXT:\n"

    def user_prompt_budget(self, *, system_prompt: str, agent_id: str, task_id: str) -> int:
        """Return the exact remaining user-prompt budget under the gateway limit."""
        prefix = self._task_prefix(system_prompt, agent_id, task_id)
        return max(0, self.MAX_TASK_CODE_UNITS - (len(prefix.encode("utf-16-le")) // 2))

    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str:
        if not self._token: raise ProviderError("AI Studio gateway token is not configured in the runtime host.")
        task = self._task_prefix(system_prompt, agent_id, task_id) + user_prompt
        if len(task.encode("utf-16-le")) // 2 > self.MAX_TASK_CODE_UNITS:
            raise ProviderError("Gateway task exceeds the 15,000 UTF-16-code-unit limit.")
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
            status = str(item.get("status", "")).strip().upper() if isinstance(item, dict) else ""
            is_live = status.startswith("LIVE") and not any(marker in status for marker in ("MOCK", "FALLBACK", "DELIVERED", "NOT LIVE"))
            if isinstance(item,dict) and isinstance(item.get("text"),str) and item["text"].strip() and is_live:
                return ProviderText(
                    item["text"].strip(),
                    {
                        "provider": key,
                        "label": str(item.get("label") or key),
                        "model": str(item.get("model") or "provider model"),
                        "status": str(item.get("status") or status),
                    },
                )
        raise ProviderError("Gateway returned no live provider response; simulated or failed output was rejected.")

def reviewer_provider_from_env(primary_provider):
    """Build a reviewer on a distinct model route; never silently reuse the worker provider."""
    requested = os.getenv("UNEXPECTED_REVIEW_PROVIDER", "").strip().lower()
    if not requested:
        return None
    if requested in ("ai_studio_gateway", "unexpected_gateway", "unexpected-ai-studio"):
        endpoint = os.getenv("UNEXPECTED_REVIEW_GATEWAY_URL", os.getenv(
            "UNEXPECTED_GATEWAY_URL", "https://unexpected-ai-studio.onrender.com/orchestrate"))
        token = os.getenv("UNEXPECTED_REVIEW_GATEWAY_TOKEN") or os.getenv("UNEXPECTED_GATEWAY_TOKEN", "")
        mode = os.getenv("UNEXPECTED_REVIEW_GATEWAY_MODE", "claude").strip().lower()
        reviewer = AIStudioGatewayProvider(
            endpoint, token, mode=mode,
            default_timeout=float(os.getenv("UNEXPECTED_REVIEW_GATEWAY_TIMEOUT_SECONDS", "200")),
        )
        if not reviewer.configured:
            raise ProviderError("Independent reviewer gateway token is not configured in the runtime host.")
        same_gateway = (
            isinstance(primary_provider, AIStudioGatewayProvider)
            and primary_provider.endpoint == reviewer.endpoint
        )
        if same_gateway and (
            "both" in (primary_provider.mode, reviewer.mode)
            or primary_provider.mode == reviewer.mode
        ):
            raise ProviderError("Reviewer route must use a different live model provider than the primary route.")
        reviewer.independence_label = f"{reviewer.name}/{reviewer.mode}"
        return reviewer
    if requested in ("openai_compatible", "openai-compatible"):
        reviewer = OpenAICompatibleProvider(
            os.getenv("UNEXPECTED_REVIEW_BASE_URL", ""),
            os.getenv("UNEXPECTED_REVIEW_MODEL", ""),
            os.getenv("UNEXPECTED_REVIEW_API_KEY", ""),
            float(os.getenv("UNEXPECTED_REVIEW_TIMEOUT_SECONDS", "60")),
        )
        if isinstance(primary_provider, OpenAICompatibleProvider) and primary_provider.base_url == reviewer.base_url and primary_provider.model == reviewer.model:
            raise ProviderError("Reviewer route must not use the primary provider endpoint and model.")
        reviewer.independence_label = f"{reviewer.name}/{reviewer.model}"
        return reviewer
    raise ProviderError("UNEXPECTED_REVIEW_PROVIDER must be ai_studio_gateway or openai_compatible.")


def provider_from_env():
    mode=os.getenv("UNEXPECTED_PROVIDER","mock").strip().lower()
    if mode=="mock": return DeterministicMockProvider()
    if mode in ("openai_compatible","openai-compatible"):
        return OpenAICompatibleProvider(os.getenv("UNEXPECTED_BASE_URL",""),os.getenv("UNEXPECTED_MODEL",""),os.getenv("UNEXPECTED_API_KEY",""),float(os.getenv("UNEXPECTED_DEFAULT_TIMEOUT_SECONDS","30")))
    if mode in ("ai_studio_gateway","unexpected_gateway","unexpected-ai-studio"):
        return AIStudioGatewayProvider(os.getenv("UNEXPECTED_GATEWAY_URL","https://unexpected-ai-studio.onrender.com/orchestrate"),os.getenv("UNEXPECTED_GATEWAY_TOKEN",""),mode=os.getenv("UNEXPECTED_GATEWAY_MODE","openai"),default_timeout=float(os.getenv("UNEXPECTED_GATEWAY_TIMEOUT_SECONDS","200")))
    raise ProviderError(f"Unsupported UNEXPECTED_PROVIDER mode: {mode}")
