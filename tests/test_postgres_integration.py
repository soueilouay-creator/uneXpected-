from __future__ import annotations

import os
import uuid
import json
import tempfile
import threading
import urllib.request
import urllib.error
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from unexpected_runtime.models import TaskRequest
from unexpected_runtime.postgres_approval_ledger import PostgresApprovalLedger
from unexpected_runtime.postgres_storage import PostgresStateStore
from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.http_api import create_server


DSN = os.getenv("TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "TEST_POSTGRES_DSN is only provided by the ephemeral CI PostgreSQL service")
class PostgresRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgresStateStore(DSN)
        self.prefix = "ci-" + uuid.uuid4().hex[:12]
        self.agent = "orchestrator"

    def test_state_store_task_memory_knowledge_audit_and_queue(self):
        request = TaskRequest.create(
            self.agent, "PostgreSQL integration task",
            inputs={"scope": "isolated-ci"},
            source_refs=("ci:test",),
            provider_route="mock",
        )
        self.store.enqueue(request)
        task = self.store.get_task(request.task_id)
        self.assertEqual(task["status"], "queued")
        payload = __import__("json").loads(task["payload_json"])
        self.assertEqual(payload["provider_route"], "mock")

        claimed = self.store.claim_next()
        self.assertEqual(claimed["task_id"], request.task_id)
        result = {"task_id": request.task_id, "status": "completed", "output": "stored"}
        self.assertTrue(self.store.mark_task(request.task_id, "completed", result))
        self.assertEqual(self.store.list_tasks(10)[0]["result"], result)

        self.store.set_memory(self.agent, self.prefix, {"remember": True})
        self.assertEqual(self.store.get_memory(self.agent, self.prefix), {"remember": True})
        self.assertIn(self.prefix, self.store.memory_keys(self.agent))

        knowledge_id = self.store.add_knowledge("ci:test", self.prefix + " reviewed fact")
        self.store.approve_knowledge(knowledge_id, "ci-reviewer")
        knowledge = self.store.query_knowledge(10)
        self.assertTrue(any(item["knowledge_id"] == knowledge_id for item in knowledge))

        outcome_id = self.store.record_outcome(self.agent, request.task_id, True, "CI verified", ["ci:test"])
        self.assertTrue(outcome_id)
        events = self.store.events(100)
        self.assertTrue(any(event["task_id"] == request.task_id for event in events))
        self.assertTrue(self.store.check_health())

    def test_state_store_baselines_versions_proposals_and_capabilities(self):
        report = {"score": 0.9, "critical_checks": {"safety": True}, "provider_mode": "mock"}
        self.store.set_baseline(
            self.agent, self.prefix, report,
            active_version="1.0.0", instruction_sha256="a" * 64, report_sha256="b" * 64,
        )
        self.assertEqual(self.store.get_baseline(self.agent, self.prefix), report)
        self.assertEqual(self.store.get_baseline_evidence(self.agent, self.prefix)["active_version"], "1.0.0")

        self.store.ensure_base_version(self.agent, self.prefix, "baseline instruction")
        active = self.store.active_version(self.agent, self.prefix, "baseline instruction")
        self.assertEqual(active["version"], self.prefix)
        self.store.promote_version(self.agent, self.prefix + "-next", "candidate", "CI candidate")
        self.assertEqual(self.store.active_version(self.agent, self.prefix, "ignored")["version"], self.prefix + "-next")
        self.store.rollback_version(self.agent, self.prefix, "CI rollback")
        self.assertEqual(self.store.active_version(self.agent, self.prefix, "ignored")["version"], self.prefix)

        proposal_id = self.prefix + "-proposal"
        proposal = {
            "proposal_id": proposal_id,
            "agent_id": self.agent,
            "base_version": self.prefix,
            "candidate_version": self.prefix + "-candidate",
            "candidate_instruction": "candidate instruction",
            "changes": "CI proposal",
            "protected_change": False,
            "benchmark_id": self.prefix,
            "status": "pending",
            "evaluation": None,
            "protected_fields": [],
            "evaluation_context": {},
        }
        self.store.save_proposal(proposal)
        self.assertEqual(self.store.get_proposal(proposal_id)["candidate_instruction"], "candidate instruction")
        self.assertTrue(any(item["proposal_id"] == proposal_id for item in self.store.list_proposals(10)))
        self.store.update_proposal(proposal_id, "evaluated", {"passed": True})
        self.assertEqual(self.store.get_proposal(proposal_id)["status"], "evaluated")

        capability_id = self.prefix + "-capability"
        capability = {"capability_id": capability_id, "status": "registered", "source": "ci"}
        self.store.save_capability(capability)
        self.assertEqual(self.store.get_capability(capability_id), capability)
        changed = dict(capability, status="disabled")
        self.assertTrue(self.store.update_capability(changed, "registered"))
        self.assertEqual(self.store.list_capabilities("disabled")[0]["capability_id"], capability_id)

    def test_postgres_single_flight_idempotency_and_replay(self):
        key = self.prefix + "-idempotency"
        digest = "c" * 64
        with ThreadPoolExecutor(max_workers=12) as pool:
            claims = list(pool.map(
                lambda index: self.store.claim_idempotency(key, digest, self.prefix + "-task-" + str(index)),
                range(24),
            ))
        self.assertEqual(sum(item["state"] == "claimed" for item in claims), 1)
        self.assertEqual(sum(item["state"] == "running" for item in claims), 23)
        task_id = next(item["task_id"] for item in claims if item["state"] == "claimed")
        result = {"task_id": task_id, "status": "completed", "output": "one execution"}
        self.assertTrue(self.store.complete_idempotency(key, task_id, result))
        replay = self.store.claim_idempotency(key, digest, self.prefix + "-replay")
        self.assertEqual(replay["state"], "completed")
        self.assertEqual(replay["result"], result)
        with self.assertRaises(ValueError):
            self.store.claim_idempotency(key, "d" * 64, self.prefix + "-changed")

    def test_one_python_command_center_uses_postgres_for_real_api_lifecycle(self):
        token = "ci-command-center-token-" + uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as state_dir, patch.dict(os.environ, {
            "UNEXPECTED_STORAGE_BACKEND": "postgres",
            "UNEXPECTED_APPROVAL_LEDGER_BACKEND": "postgres",
            "DATABASE_URL": DSN,
            "UNEXPECTED_RUNTIME_API_TOKEN": token,
            "UNEXPECTED_DEFAULT_PROVIDER": "mock",
            "UNEXPECTED_STATE_DIR": state_dir,
        }):
            coordinator = Coordinator(state_dir=state_dir, max_workers=2, max_retries=0)
            server = create_server(coordinator=coordinator, api_token=token)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:" + str(server.server_address[1])
            headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
            try:
                with urllib.request.urlopen(base + "/health", timeout=5) as response:
                    health = json.loads(response.read())
                    self.assertEqual(response.status, 200)
                    self.assertTrue(health["ok"])
                    self.assertEqual(health["storage"], "ready")

                with urllib.request.urlopen(urllib.request.Request(base + "/v1/status", headers=headers), timeout=5) as response:
                    status = json.loads(response.read())
                    self.assertEqual(status["storage"]["backend"], "postgres")
                    self.assertEqual(status["registered_agents"], 38)

                payload = {
                    "agent_id": self.agent,
                    "objective": "Verify the unified PostgreSQL command center",
                    "inputs": {"source": "ephemeral-ci"},
                    "provider_route": "mock",
                    "idempotency_key": self.prefix + "-http-idempotency",
                }
                body = json.dumps(payload).encode()
                request = urllib.request.Request(base + "/v1/invoke", data=body, headers=headers, method="POST")
                with urllib.request.urlopen(request, timeout=20) as response:
                    result = json.loads(response.read())
                    self.assertEqual(response.status, 200)
                    self.assertEqual(result["status"], "completed")
                    task_id = result["task_id"]

                detail_request = urllib.request.Request(base + "/v1/tasks/" + task_id, headers=headers)
                with urllib.request.urlopen(detail_request, timeout=5) as response:
                    detail = json.loads(response.read())["task"]
                    self.assertEqual(detail["provider_route"], "mock")
                    self.assertEqual(detail["result"]["status"], "completed")

                events_request = urllib.request.Request(base + "/v1/events?task_id=" + task_id, headers=headers)
                with urllib.request.urlopen(events_request, timeout=5) as response:
                    events = json.loads(response.read())["items"]
                    provider_events = [event for event in events if event["event_type"] == "provider_used"]
                    self.assertTrue(provider_events)
                    self.assertTrue(json.loads(provider_events[0]["payload_json"])["mock"])

                replay_request = urllib.request.Request(base + "/v1/invoke", data=body, headers=headers, method="POST")
                with urllib.request.urlopen(replay_request, timeout=10) as response:
                    replay = json.loads(response.read())
                    self.assertTrue(replay["idempotent_replay"])
                    self.assertEqual(replay["task_id"], task_id)

                with urllib.request.urlopen(base + "/", timeout=5) as response:
                    self.assertIn(b'id="proposal-form"', response.read())
                try:
                    urllib.request.urlopen(base + "/mobile/", timeout=5)
                    self.fail("The v8 application must not expose a phone/PWA route.")
                except urllib.error.HTTPError as error:
                    self.assertEqual(error.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                coordinator.close()

    def test_postgres_approval_ledger_consumes_one_use_approval_atomically(self):
        ledger = PostgresApprovalLedger(DSN)
        approval_id = self.prefix + "-approval"
        digest = "e" * 64
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: ledger.consume_once(approval_id, digest), range(24)))
        self.assertEqual(sum(results), 1)
        self.assertFalse(ledger.consume_once(approval_id, digest))
        self.assertFalse(ledger.consume_once(approval_id, "f" * 64))


if __name__ == "__main__":
    unittest.main(verbosity=2)
