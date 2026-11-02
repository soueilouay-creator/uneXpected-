from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.http_api import create_server
from unexpected_runtime.providers import DeterministicMockProvider


ROOT = Path(__file__).resolve().parents[1]


class CommandCenterAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.coordinator = Coordinator(
            state_dir=self.tmp.name,
            provider=DeterministicMockProvider(),
            max_workers=2,
            max_retries=0,
        )
        self.token = "command-center-test-token-" + "x" * 32
        self.server = create_server(
            coordinator=self.coordinator,
            api_token=self.token,
            host="127.0.0.1",
            port=0,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.coordinator.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, token=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=8)
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        raw = response.read()
        content_type = response.getheader("Content-Type", "")
        conn.close()
        if "application/json" in content_type and raw:
            return response.status, json.loads(raw)
        return response.status, raw.decode("utf-8", errors="replace")

    def test_root_serves_command_center_without_phone_app(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("<html", body.lower())
        self.assertIn("uneXpected", body)
        self.assertNotIn("/mobile/", body)
        self.assertNotIn("service-worker", body.lower())
        self.assertNotIn("manifest.webmanifest", body.lower())

    def test_static_assets_are_served_from_fixed_web_root(self):
        css_status, css = self.request("GET", "/assets/styles.css")
        js_status, js = self.request("GET", "/assets/app.js")
        self.assertEqual(css_status, 200)
        self.assertEqual(js_status, 200)
        self.assertIn("text/css", self._content_type("/assets/styles.css"))
        self.assertIn("javascript", self._content_type("/assets/app.js"))
        self.assertIn("fetch(", js)
        self.assertEqual(self.request("GET", "/assets/../../.env")[0], 404)
        self.assertEqual(self.request("GET", "/assets/%2e%2e/%2e%2e/.env")[0], 404)
        self.assertEqual(self.request("GET", "/mobile/")[0], 404)

    def _content_type(self, path):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=8)
        conn.request("GET", path)
        response = conn.getresponse()
        value = response.getheader("Content-Type", "")
        response.read()
        conn.close()
        return value

    def test_command_center_read_apis_require_bearer_auth(self):
        routes = (
            "/v1/agents",
            "/v1/tasks",
            "/v1/events",
            "/v1/capabilities",
            "/v1/improvements",
            "/v1/providers",
            "/v1/approvals",
        )
        for route in routes:
            with self.subTest(route=route):
                self.assertEqual(self.request("GET", route)[0], 401)

    def test_command_center_read_apis_return_structured_data(self):
        routes = (
            "/v1/agents",
            "/v1/tasks",
            "/v1/events",
            "/v1/capabilities",
            "/v1/improvements",
            "/v1/providers",
            "/v1/approvals",
        )
        for route in routes:
            with self.subTest(route=route):
                status, body = self.request("GET", route, token=self.token)
                self.assertEqual(status, 200)
                self.assertIsInstance(body, dict)
                self.assertIn("items" if route != "/v1/providers" else "providers", body)

    def test_health_is_minimal_and_never_discloses_secret_or_internal_paths(self):
        status, body = self.request("GET", "/health")
        self.assertEqual(status, 200)
        serialized = json.dumps(body).lower()
        for forbidden in (
            "api_token",
            "database_url",
            "openai_api_key",
            "anthropic_api_key",
            "state_db",
            "/tmp/",
            "approval_ledger_path",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_agent_registry_reports_exactly_38_roles(self):
        status, body = self.request("GET", "/v1/agents", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body.get("count"), 38)
        self.assertEqual(len(body.get("items", [])), 38)


if __name__ == "__main__":
    unittest.main(verbosity=2)
