from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from unexpected_runtime.providers import (
    AnthropicProvider,
    DeterministicMockProvider,
    OpenAICompatibleProvider,
    ProviderError,
    ProviderRouter,
    provider_router_from_env,
)


class FakeResponse:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")
    def read(self, size=-1):
        return self.raw if size < 0 else self.raw[:size]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, payload):
        self.response = FakeResponse(payload)
        self.request = None
        self.timeout = None
    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return self.response


class AnthropicProviderTests(unittest.TestCase):
    def test_anthropic_uses_messages_api_headers_and_bounded_payload(self):
        opener = FakeOpener({"content": [{"type": "text", "text": "Claude answer"}], "model": "claude-test"})
        provider = AnthropicProvider("anthropic-test-key", "claude-test-model")
        with patch("unexpected_runtime.providers.urllib.request.build_opener", return_value=opener):
            result = provider.generate(system_prompt="System", user_prompt="Task", agent_id="research-scout", task_id="task-1", timeout=9)
        self.assertEqual(result, "Claude answer")
        self.assertEqual(opener.request.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(opener.request.get_header("X-api-key"), "anthropic-test-key")
        self.assertEqual(opener.request.get_header("Anthropic-version"), "2023-06-01")
        body = json.loads(opener.request.data)
        self.assertEqual(body["model"], "claude-test-model")
        self.assertEqual(body["max_tokens"], 1024)
        self.assertEqual(body["system"], "System")
        self.assertEqual(body["messages"][0]["content"], "Task")

    def test_anthropic_missing_key_malformed_response_and_http_failure_fail_closed(self):
        with self.assertRaises(ProviderError):
            AnthropicProvider("", "claude-test-model")
        provider = AnthropicProvider("anthropic-test-key", "claude-test-model")
        malformed = FakeOpener({"content": [{"type": "image", "source": {}}]})
        with patch("unexpected_runtime.providers.urllib.request.build_opener", return_value=malformed):
            with self.assertRaises(ProviderError):
                provider.generate(system_prompt="S", user_prompt="U", agent_id="a", task_id="t", timeout=5)

    def test_anthropic_disables_redirects_and_rejects_oversized_response(self):
        from unexpected_runtime.providers import _NoRedirect
        from urllib.request import Request
        handler = _NoRedirect()
        request = Request("https://api.anthropic.com/v1/messages", method="POST")
        self.assertIsNone(handler.redirect_request(request, None, 302, "redirect", {}, "https://attacker.example"))
        provider = AnthropicProvider("anthropic-test-key", "claude-test-model")
        opener = FakeOpener({"content": [{"type": "text", "text": "x" * 2000000}]})
        with patch("unexpected_runtime.providers.urllib.request.build_opener", return_value=opener):
            with self.assertRaises(ProviderError):
                provider.generate(system_prompt="S", user_prompt="U", agent_id="a", task_id="t", timeout=5)


class ProviderRouterTests(unittest.TestCase):
    def test_routes_resolve_only_registered_providers(self):
        mock = DeterministicMockProvider()
        openai = OpenAICompatibleProvider("https://api.openai.com/v1", "gpt-test", "o" * 48)
        router = ProviderRouter({"mock": mock, "openai": openai}, default_route="mock")
        self.assertIs(router.resolve("mock"), mock)
        self.assertIs(router.resolve("openai"), openai)
        with self.assertRaises(ProviderError):
            router.resolve("anthropic")

    def test_provider_status_never_exposes_credentials(self):
        mock = DeterministicMockProvider()
        router = ProviderRouter({"mock": mock}, default_route="mock")
        status = router.status()
        self.assertEqual(status[0]["id"], "mock")
        self.assertTrue(status[0]["configured"])
        self.assertFalse(status[0]["verified"])
        self.assertNotIn("api_key", json.dumps(status).lower())
        self.assertNotIn("secret", json.dumps(status).lower())

    def test_concurrent_route_resolution_does_not_mutate_default_provider(self):
        class TaggedProvider:
            def __init__(self, name):
                self.name = name
                self.configured = True
                self.retry_safe = False
            def generate(self, **kwargs):
                return self.name
        router = ProviderRouter(
            {"openai": TaggedProvider("openai"), "anthropic": TaggedProvider("anthropic")},
            default_route="openai",
        )
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(router.resolve, route) for route in ("openai", "anthropic")]
        self.assertEqual([future.result().name for future in futures], ["openai", "anthropic"])
        self.assertEqual(router.resolve(None).name, "openai")

    def test_factory_keeps_mock_default_and_registers_only_configured_providers(self):
        env = {
            "UNEXPECTED_PROVIDER": "mock",
            "OPENAI_API_KEY": "o" * 48,
            "OPENAI_MODEL": "gpt-test",
            "ANTHROPIC_API_KEY": "a" * 48,
            "ANTHROPIC_MODEL": "claude-test",
            "OPENROUTER_API_KEY": "",
        }
        with patch.dict("os.environ", env, clear=True):
            router = provider_router_from_env()
        self.assertEqual(router.default_route, "mock")
        self.assertEqual(set(router.providers), {"mock", "openai", "anthropic"})
        self.assertNotIn("openrouter", router.providers)

    def test_openrouter_is_registered_only_when_configured_and_uses_openai_compatible_adapter(self):
        env = {
            "UNEXPECTED_PROVIDER": "mock",
            "OPENROUTER_API_KEY": "r" * 48,
            "OPENROUTER_MODEL": "openrouter/free",
        }
        with patch.dict("os.environ", env, clear=True):
            router = provider_router_from_env()
        provider = router.resolve("openrouter")
        self.assertIsInstance(provider, OpenAICompatibleProvider)
        self.assertIn("openrouter.ai", provider.base_url)
        self.assertEqual(provider.model, "openrouter/free")


if __name__ == "__main__":
    unittest.main(verbosity=2)
