import unittest
from unexpected_runtime.providers import AIStudioGatewayProvider, ProviderError


class UnifiedGatewayLoopbackTests(unittest.TestCase):
    def test_gateway_accepts_http_only_for_loopback_internal_hop(self):
        provider = AIStudioGatewayProvider(
            "http://127.0.0.1:10000/orchestrate",
            "internal-test-token-which-is-long-enough",
        )
        self.assertEqual(provider.endpoint, "http://127.0.0.1:10000/orchestrate")

    def test_gateway_rejects_cleartext_http_to_non_loopback_hosts(self):
        with self.assertRaises(ProviderError):
            AIStudioGatewayProvider(
                "http://gateway.example/orchestrate",
                "internal-test-token-which-is-long-enough",
            )

    def test_gateway_rejects_embedded_credentials_even_on_loopback(self):
        with self.assertRaises(ProviderError):
            AIStudioGatewayProvider(
                "http://user:password@127.0.0.1:10000/orchestrate",
                "internal-test-token-which-is-long-enough",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
