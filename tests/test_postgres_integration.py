from __future__ import annotations

import os
import uuid
import unittest
from concurrent.futures import ThreadPoolExecutor

from unexpected_runtime.models import TaskRequest
from unexpected_runtime.postgres_approval_ledger import PostgresApprovalLedger
from unexpected_runtime.postgres_storage import PostgresStateStore


DSN = os.getenv("TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "TEST_POSTGRES_DSN is only provided by the ephemeral CI PostgreSQL service")
class PostgresRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgresStateStore(DSN)
        self.prefix = "ci-" + uuid.uuid4().hex[:12]
        self.agent = "orchestrator"

    def tearDown(self):
        self.store.close()

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
