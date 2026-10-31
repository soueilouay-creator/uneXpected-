from __future__ import annotations
import http.client, json, tempfile, threading, unittest
from unittest.mock import patch
from unexpected_runtime.providers import AIStudioGatewayProvider, ProviderError, provider_from_env
from unexpected_runtime.http_api import create_server
from unexpected_runtime.coordinator import Coordinator

class Response:
    def __init__(self,obj): self.data=json.dumps(obj).encode()
    def read(self,n=-1): return self.data if n<0 else self.data[:n]
    def __enter__(self): return self
    def __exit__(self,*a): return False
class Opener:
    def __init__(self,obj): self.response=Response(obj); self.request=None
    def open(self,req,timeout): self.request=req; return self.response

class ProviderTests(unittest.TestCase):
    def test_live_gateway_response_and_bearer_auth(self):
        opener=Opener({"ok":True,"results":{"openai":{"status":"LIVE · verified response","text":"real answer","model":"gpt-4.1"}}})
        p=AIStudioGatewayProvider("https://unexpected-ai-studio.onrender.com/orchestrate","g"*48,mode="openai")
        with patch("unexpected_runtime.providers.urllib.request.build_opener",return_value=opener):
            out=p.generate(system_prompt="S",user_prompt="U",agent_id="orchestrator",task_id="t",timeout=12)
        self.assertIn("real answer",out); self.assertEqual(opener.request.get_header("Authorization"),"Bearer "+"g"*48)
    def test_dual_mode_prefers_live_synthesis(self):
        p=AIStudioGatewayProvider("https://gateway.example/orchestrate","g"*48,mode="both")
        op=Opener({"ok":True,"results":{"synthesis":{"status":"LIVE · verified response","text":"combined"}}})
        with patch("unexpected_runtime.providers.urllib.request.build_opener",return_value=op):
            self.assertIn("combined",p.generate(system_prompt="S",user_prompt="U",agent_id="a",task_id="t",timeout=5))
    def test_missing_token_and_non_live_result_fail_closed(self):
        p=AIStudioGatewayProvider("https://gateway.example/orchestrate","")
        with self.assertRaises(ProviderError): p.generate(system_prompt="S",user_prompt="U",agent_id="a",task_id="t",timeout=5)
        p=AIStudioGatewayProvider("https://gateway.example/orchestrate","g"*48)
        op=Opener({"ok":True,"results":{"openai":{"status":"MOCK","text":"fake"}}})
        with patch("unexpected_runtime.providers.urllib.request.build_opener",return_value=op):
            with self.assertRaises(ProviderError): p.generate(system_prompt="S",user_prompt="U",agent_id="a",task_id="t",timeout=5)
    def test_rejects_insecure_url_bad_mode_and_large_task(self):
        for url in ("http://gateway.example","https://u:p@gateway.example/x"):
            with self.assertRaises(ProviderError): AIStudioGatewayProvider(url,"g"*48)
        with self.assertRaises(ProviderError): AIStudioGatewayProvider("https://gateway.example","g"*48,mode="other")
        p=AIStudioGatewayProvider("https://gateway.example","g"*48)
        with patch("unexpected_runtime.providers.urllib.request.build_opener") as build:
            with self.assertRaises(ProviderError): p.generate(system_prompt="x"*15001,user_prompt="u",agent_id="a",task_id="t",timeout=5)
            build.assert_not_called()
    def test_factory_uses_gateway_config(self):
        env={"UNEXPECTED_PROVIDER":"ai_studio_gateway","UNEXPECTED_GATEWAY_URL":"https://gateway.example","UNEXPECTED_GATEWAY_TOKEN":"g"*48}
        with patch.dict("os.environ",env,clear=True):
            self.assertIsInstance(provider_from_env(),AIStudioGatewayProvider)

class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.coord=Coordinator(state_dir=self.tmp.name,provider=__import__("unexpected_runtime.providers",fromlist=["DeterministicMockProvider"]).DeterministicMockProvider(),max_workers=1,max_retries=0)
        self.server=create_server(coordinator=self.coord,api_token="a"*48,host="127.0.0.1",port=0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.host,self.port=self.server.server_address
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=2); self.coord.close(); self.tmp.cleanup()
    def request(self,method,path,body=None,token="a"*48):
        conn=http.client.HTTPConnection(self.host,self.port,timeout=8); headers={}
        if token: headers["Authorization"]="Bearer "+token
        if body is not None: headers["Content-Type"]="application/json"
        conn.request(method,path,json.dumps(body) if body is not None else None,headers)
        res=conn.getresponse(); data=res.read(); conn.close()
        return res.status,json.loads(data) if data else {}
    def test_health_is_public_without_secret_values(self):
        code,data=self.request("GET","/health",token="")
        self.assertEqual(code,200); self.assertNotIn("api_token",data); self.assertNotIn("state_db",data)
    def test_auth_and_status(self):
        self.assertEqual(self.request("GET","/v1/status",token="")[0],401)
        self.assertEqual(self.request("GET","/v1/status")[0],200)
    def test_unprivileged_invocation_succeeds(self):
        code,data=self.request("POST","/v1/invoke",{"agent_id":"orchestrator","objective":"Run a safe smoke test"})
        self.assertEqual(code,200); self.assertEqual(data["result"]["status"],"completed")
    def test_privileged_fields_and_bad_routes_are_rejected(self):
        for payload in ({"agent_id":"orchestrator","objective":"x","required_permissions":["publish"]},{"agent_id":"orchestrator","objective":"x","approval":{"approver":"owner"}}):
            self.assertEqual(self.request("POST","/v1/invoke",payload)[0],400)
        self.assertEqual(self.request("GET","/missing")[0],404)
    def test_locked_without_a_strong_api_token(self):
        s=create_server(coordinator=self.coord,api_token="short",host="127.0.0.1",port=0)
        t=threading.Thread(target=s.serve_forever,daemon=True); t.start()
        try:
            c=http.client.HTTPConnection("127.0.0.1",s.server_address[1]); c.request("GET","/v1/status")
            r=c.getresponse(); self.assertEqual(r.status,503); c.close()
        finally: s.shutdown(); s.server_close(); t.join(timeout=2)
    def test_http_invocation_reaches_gateway_provider(self):
        op=Opener({"ok":True,"results":{"openai":{"status":"LIVE · verified response","text":"end-to-end live-shaped result","model":"gpt-4.1"}}})
        p=AIStudioGatewayProvider("https://gateway.example/orchestrate","g"*48,mode="openai")
        with tempfile.TemporaryDirectory() as state:
            c=Coordinator(state_dir=state,provider=p,max_workers=1,max_retries=0)
            s=create_server(coordinator=c,api_token="a"*48,host="127.0.0.1",port=0)
            t=threading.Thread(target=s.serve_forever,daemon=True); t.start()
            try:
                with patch("unexpected_runtime.providers.urllib.request.build_opener",return_value=op):
                    conn=http.client.HTTPConnection("127.0.0.1",s.server_address[1],timeout=5)
                    conn.request("POST","/v1/invoke",json.dumps({"agent_id":"orchestrator","objective":"test"}),{"Authorization":"Bearer "+"a"*48,"Content-Type":"application/json"})
                    r=conn.getresponse(); result=json.loads(r.read()); conn.close()
                self.assertEqual(r.status,200,result); self.assertEqual(result["result"]["status"],"completed",result); self.assertIn("end-to-end live-shaped result",result["result"]["output"])
            finally: s.shutdown(); s.server_close(); t.join(timeout=2); c.close()

if __name__=="__main__": unittest.main(verbosity=2)
