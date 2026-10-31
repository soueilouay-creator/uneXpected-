from __future__ import annotations
from typing import Protocol
import json, os, urllib.request, urllib.error

class ProviderError(RuntimeError): pass
class Provider(Protocol):
    name: str
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str: ...

class DeterministicMockProvider:
    name='deterministic-mock'
    def __init__(self): self.calls=0; self.requests=[]
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str:
        self.calls+=1; self.requests.append({'system_prompt':system_prompt,'user_prompt':user_prompt,'agent_id':agent_id,'task_id':task_id})
        objective=user_prompt.replace('\n',' ')[:180]
        return f'MOCK_OK agent={agent_id} task={task_id} objective={objective}. This deterministic response verifies runtime plumbing only.'

class OpenAICompatibleProvider:
    name='openai-compatible'
    def __init__(self, base_url: str, model: str, api_key: str, default_timeout: float=30.0):
        if not base_url or not model or not api_key: raise ProviderError('OpenAI-compatible provider requires base URL, model and API key in environment; no secret belongs in chat.')
        self.base_url=base_url.rstrip('/')
        if not self.base_url.endswith('/chat/completions'): self.base_url += '/chat/completions'
        self.model=model; self._api_key=api_key; self.default_timeout=default_timeout
    def generate(self, *, system_prompt: str, user_prompt: str, agent_id: str, task_id: str, timeout: float) -> str:
        body={'model':self.model,'messages':[{'role':'system','content':system_prompt},{'role':'user','content':user_prompt}],
              'metadata':{'agent_id':agent_id,'task_id':task_id}}
        req=urllib.request.Request(self.base_url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':f'Bearer {self._api_key}'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=min(timeout,self.default_timeout)) as resp: data=json.loads(resp.read().decode())
        except Exception as e:
            # Do not include request headers or key in the error message.
            raise ProviderError(f'Provider request failed ({type(e).__name__}); inspect host-side logs without exposing secrets.') from None
        try: return str(data['choices'][0]['message']['content'])
        except Exception: raise ProviderError('Provider returned an unexpected response schema.') from None

def provider_from_env():
    mode=os.getenv('UNEXPECTED_PROVIDER','mock').strip().lower()
    if mode=='mock': return DeterministicMockProvider()
    if mode in ('openai_compatible','openai-compatible'):
        return OpenAICompatibleProvider(os.getenv('UNEXPECTED_BASE_URL',''),os.getenv('UNEXPECTED_MODEL',''),os.getenv('UNEXPECTED_API_KEY',''),float(os.getenv('UNEXPECTED_DEFAULT_TIMEOUT_SECONDS','30')))
    raise ProviderError(f'Unsupported UNEXPECTED_PROVIDER mode: {mode}')
