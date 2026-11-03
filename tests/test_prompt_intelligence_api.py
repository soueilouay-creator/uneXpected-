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


class PromptIntelligenceAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = DeterministicMockProvider()
        self.coordinator = Coordinator(
            manifest_path=Path(__file__).resolve().parents[1] / "agent_manifest.json",
            state_dir=Path(self.temp.name) / "state",
            provider=self.provider,
            max_retries=0,
            approval_verifier=None,
        )
        # The API test exercises the fail-closed boundary even on hosts that may
        # have a development approval adapter configured in their environment.
        self.coordinator.approval_verifier = None
        self.coordinator.permissions.approval_verifier = None
        self.token = "prompt-intelligence-api-" + "x" * 32
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

    def register_source(self, source_id="api-fixture"):
        status, payload = self.request(
            "POST", "/v1/prompt-intelligence/sources",
            body={
                "source_id": source_id,
                "name": "API Fixture Prompts",
                "canonical_url": "https://example.com/prompts",
                "publisher": "Example Publisher",
                "source_type": "website",
                "attribution": "Example Publisher prompt metadata",
            },
            token=self.token,
        )
        self.assertEqual(status, 201, payload)
        self.assertEqual(payload["source"]["rights_status"], "unknown")
        self.assertEqual(payload["source"]["retention_policy"], "metadata_only")
        return payload["source"]

    def import_prompt(self, source_id="api-fixture"):
        source = next((item for item in self.coordinator.prompt_intelligence.list_sources()
                       if item["source_id"] == source_id), None)
        if source and source.get("status") == "staged":
            self.review_metadata_source(source_id)
        status, payload = self.request(
            "POST", "/v1/prompt-intelligence/import",
            body={
                "source_id": source_id,
                "records": [{
                    "external_id": "sales-draft-1",
                    "title": "Prepare a practical sales follow-up",
                    "category": "Sales",
                    "category_id": "sales",
                    "source_url": "https://example.com/prompts/sales-draft-1",
                }],
            },
            token=self.token,
        )
        self.assertEqual(status, 201, payload)
        return payload["items"][0]["prompt_id"]

    def review_metadata_source(self, source_id="api-fixture"):
        status, payload = self.request(
            "POST", "/v1/prompt-intelligence/sources/" + source_id + "/review",
            body={
                "rights_status": "unknown",
                "retention_policy": "metadata_only",
                "evidence_url": None,
                "attribution": "Example Publisher prompt metadata",
            },
            token=self.token,
        )
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["source"]["status"], "reviewed")

    def test_source_registry_requires_auth_and_stages_metadata_only(self):
        self.assertEqual(self.request("GET", "/v1/prompt-intelligence/sources")[0], 401)
        self.assertEqual(self.request(
            "POST", "/v1/prompt-intelligence/sources",
            body={"source_id": "unauth", "name": "No Auth", "canonical_url": "https://example.com",
                  "publisher": "Example", "attribution": "Example"},
        )[0], 401)
        self.register_source()
        status, payload = self.request("GET", "/v1/prompt-intelligence/sources", token=self.token)
        self.assertEqual(status, 200)
        self.assertTrue(any(item["source_id"] == "api-fixture" for item in payload["items"]))

    def test_import_is_staged_and_body_without_rights_is_rejected(self):
        self.register_source()
        status, payload = self.request(
            "POST", "/v1/prompt-intelligence/import",
            body={"source_id": "api-fixture", "records": [{
                "external_id": "unlicensed-body", "title": "Unsafe retention",
                "category": "Sales", "category_id": "sales",
                "body": "Third party text without rights evidence",
            }]},
            token=self.token,
        )
        self.assertEqual(status, 400, payload)
        prompt_id = self.import_prompt()
        status, queue = self.request("GET", "/v1/prompt-intelligence/review-queue", token=self.token)
        self.assertEqual(status, 200)
        self.assertTrue(any(item["prompt_id"] == prompt_id and item["status"] == "staged" for item in queue["items"]))
        self.assertIsNone(self.coordinator.store.get_prompt_version(prompt_id, 1)["body"])

    def test_review_mapping_and_activation_fail_closed_without_host_approval(self):
        self.register_source()
        prompt_id = self.import_prompt()
        self.review_metadata_source()
        status, invalid = self.request(
            "POST", "/v1/prompt-intelligence/prompts/" + prompt_id + "/review",
            body={"version": 1, "mapped_agent_id": "made-up-agent"},
            token=self.token,
        )
        self.assertEqual(status, 400, invalid)
        status, reviewed = self.request(
            "POST", "/v1/prompt-intelligence/prompts/" + prompt_id + "/review",
            body={"version": 1, "mapped_agent_id": "sales-intel"},
            token=self.token,
        )
        self.assertEqual(status, 200, reviewed)
        self.assertEqual(reviewed["review"]["status"], "ready_for_activation")
        status, details = self.request(
            "GET", "/v1/prompt-intelligence/prompts/" + prompt_id + "/activation-details?version=1",
            token=self.token,
        )
        self.assertEqual(status, 200, details)
        self.assertEqual(len(details["action_digest"]), 64)
        status, rejected = self.request(
            "POST", "/v1/prompt-intelligence/prompts/" + prompt_id + "/activate",
            body={
                "version": 1,
                "approval_id": "github-pr:123:prompt-activation-1",
                "approver": "trusted-reviewer",
                "approved_permissions": ["modify_policy"],
                "rationale": "Approve exact reviewed prompt version",
                "action_digest": details["action_digest"],
            },
            token=self.token,
        )
        self.assertEqual(status, 403, rejected)
        self.assertEqual(self.coordinator.store.get_prompt(prompt_id)["active_version"], None)

    def test_active_prompt_selection_is_role_bound_and_persisted(self):
        prompt_id = "sales-001"
        before = len(self.provider.requests)
        status, wrong_role = self.request(
            "POST", "/v1/invoke",
            body={"agent_id": "coding-engineer", "objective": "Review this prompt",
                  "prompt_id": prompt_id, "idempotency_key": "prompt-role-mismatch"},
            token=self.token,
        )
        self.assertEqual(status, 400, wrong_role)
        self.assertEqual(len(self.provider.requests), before)

        status, result = self.request(
            "POST", "/v1/invoke",
            body={"agent_id": "sales-intel", "objective": "Prepare a draft",
                  "prompt_id": prompt_id, "idempotency_key": "prompt-intelligence-seed-invoke"},
            token=self.token,
        )
        self.assertEqual(status, 200, result)
        task = self.coordinator.store.get_task(result["result"]["task_id"])
        payload = json.loads(task["payload_json"])
        binding = payload["inputs"]["__uneXpected_prompt"]
        self.assertEqual(binding["prompt_id"], prompt_id)
        self.assertEqual(binding["active_version"], 1)
        self.assertEqual(binding["source_id"], "aimoneymove-prompt-index")


if __name__ == "__main__":
    unittest.main(verbosity=2)
