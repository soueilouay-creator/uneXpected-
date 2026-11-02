import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.http_api import create_server
from unexpected_runtime.providers import DeterministicMockProvider


class WorkspaceAPITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.coordinator = Coordinator(
            manifest_path=Path(__file__).resolve().parents[1] / "agent_manifest.json",
            state_dir=self.tmp.name,
            provider=DeterministicMockProvider(),
            max_workers=2,
        )
        self.token = "workspace-api-test-token-" + ("x" * 32)
        self.server = create_server(coordinator=self.coordinator, api_token=self.token, host="127.0.0.1", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.coordinator.close()
        self.tmp.cleanup()

    def call(self, method, path, body=None, token=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Authorization": "Bearer " + (token if token is not None else self.token)}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_workspace_import_and_export_are_authenticated_and_versioned(self):
        body = {
            "schema_version": 1,
            "device_id": "device-test",
            "records": [{
                "id": "projects:project-1",
                "type": "projects",
                "payload": {"id": "project-1", "name": "Test"},
                "updated_at": "2026-11-02T10:00:00Z",
            }],
        }
        status, imported = self.call("POST", "/v1/workspace/import", body)
        self.assertEqual(status, 200)
        self.assertEqual(imported["counts"]["inserted"], 1)
        status, exported = self.call("GET", "/v1/workspace/export")
        self.assertEqual(status, 200)
        self.assertEqual(exported["schema_version"], 1)
        self.assertEqual(exported["records"][0]["id"], "projects:project-1")

    def test_workspace_import_rejects_permission_claims_and_invalid_schema(self):
        with self.assertRaises(urllib.error.HTTPError) as unauthorized:
            self.call("POST", "/v1/workspace/import", {
                "schema_version": 1, "device_id": "d", "records": [], "required_permissions": ["publish"]
            })
        self.assertEqual(unauthorized.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as bad_schema:
            self.call("POST", "/v1/workspace/import", {
                "schema_version": 2, "device_id": "d", "records": []
            })
        self.assertEqual(bad_schema.exception.code, 400)

    def test_workspace_export_requires_bearer_authentication(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.call("GET", "/v1/workspace/export", token="wrong-token")
        self.assertEqual(error.exception.code, 401)

    def test_runtime_status_and_agent_registry_are_authenticated(self):
        with self.assertRaises(urllib.error.HTTPError) as status_error:
            self.call("GET", "/v1/status", token="wrong-token")
        self.assertEqual(status_error.exception.code, 401)
        status, payload = self.call("GET", "/v1/status")
        self.assertEqual(status, 200)
        self.assertEqual(payload["registered_agents"], 38)
        status, agents = self.call("GET", "/v1/agents")
        self.assertEqual(status, 200)
        self.assertEqual(len(agents["agents"]), 38)
        self.assertTrue(any(agent["id"] == "orchestrator" for agent in agents["agents"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
