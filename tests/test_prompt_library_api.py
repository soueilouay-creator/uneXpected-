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


class PromptLibraryAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = DeterministicMockProvider()
        self.coordinator = Coordinator(
            manifest_path=Path(__file__).resolve().parents[1] / "agent_manifest.json",
            state_dir=Path(self.temp.name) / "state",
            provider=self.provider,
            max_retries=0,
        )
        self.token = "prompt-library-api-test-" + "x" * 32
        self.server = create_server(
            coordinator=self.coordinator, api_token=self.token, host="127.0.0.1", port=0
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.coordinator.close()
        self.temp.cleanup()

    def request(self, method, path, body=None, token=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=10)
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        raw = response.read()
        content_type = response.getheader("Content-Type", "")
        connection.close()
        return response.status, json.loads(raw) if "application/json" in content_type and raw else raw

    def test_catalog_requires_auth_and_returns_all_category_counts(self):
        self.assertEqual(self.request("GET", "/v1/prompts")[0], 401)
        status, payload = self.request("GET", "/v1/prompts?limit=1", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1178)
        self.assertEqual(payload["category_count"], 15)
        self.assertEqual(sum(item["count"] for item in payload["categories"]), 1178)
        self.assertEqual(len(payload["items"]), 1)
        self.assertIn("source", payload)

    def test_catalog_search_is_server_filtered_and_bounded(self):
        status, payload = self.request(
            "GET", "/v1/prompts?q=proposal&category=sales&limit=5", token=self.token
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(payload["total"], 1)
        self.assertLessEqual(len(payload["items"]), 5)
        self.assertTrue(all(item["category_id"] == "sales" for item in payload["items"]))
        self.assertTrue(all("proposal" in item["title"].lower() for item in payload["items"]))

    def test_prompt_detail_returns_only_native_template_and_source_metadata(self):
        status, payload = self.request(
            "GET", "/v1/prompts/sales-001", token=self.token
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["item"]["id"], "sales-001")
        self.assertIn("starter_instructions", payload)
        self.assertIn("aimoneymove-prompts.netlify.app", payload["item"]["source_url"])
        self.assertNotIn("original_prompt_text", payload["item"])

    def test_selected_prompt_is_bound_into_governed_invocation_and_task_record(self):
        status, response = self.request(
            "POST", "/v1/invoke",
            body={
                "agent_id": "sales-intel",
                "objective": "Prepare a tailored follow-up draft for my maintenance tracker offer.",
                "prompt_id": "sales-001",
                "inputs": {"offer": "Preventive Maintenance Tracker"},
                "idempotency_key": "prompt-library-api-invocation",
            },
            token=self.token,
        )
        self.assertEqual(status, 200, response)
        result = response["result"]
        self.assertEqual(result["status"], "completed")
        provider_payload = json.loads(self.provider.requests[-1]["user_prompt"])
        self.assertIn("prompt_id", provider_payload["inputs"]["__uneXpected_prompt"])
        self.assertEqual(
            provider_payload["inputs"]["__uneXpected_prompt"]["prompt_id"], "sales-001"
        )
        self.assertIn("source_url", provider_payload["inputs"]["__uneXpected_prompt"])
        self.assertIn("draft only", provider_payload["objective"].lower())
        detail_status, detail = self.request(
            "GET", "/v1/tasks/" + result["task_id"], token=self.token
        )
        self.assertEqual(detail_status, 200)
        self.assertEqual(
            detail["task"]["inputs"]["__uneXpected_prompt"]["prompt_id"], "sales-001"
        )

    def test_unknown_prompt_and_reserved_metadata_are_rejected_before_provider_call(self):
        count_before = len(self.provider.requests)
        invalid = [
            {"prompt_id": "unknown-prompt"},
            {"inputs": {"__uneXpected_prompt": {"prompt_id": "forged"}}},
            {"agent_id": "sales-intel", "prompt_id": "sales-001", "inputs": [["malformed", "mapping"]]},
            {"agent_id": "coding-engineer", "prompt_id": "sales-001"},
        ]
        for index, extra in enumerate(invalid):
            body = {
                "agent_id": "sales-intel",
                "objective": "Prepare a draft",
                "idempotency_key": f"invalid-prompt-{index}",
                **extra,
            }
            status, _ = self.request("POST", "/v1/invoke", body=body, token=self.token)
            self.assertEqual(status, 400)
        self.assertEqual(len(self.provider.requests), count_before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
