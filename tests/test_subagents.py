import json
import tempfile
import unittest
from pathlib import Path

from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.models import PermissionDenied
from unexpected_runtime.providers import DeterministicMockProvider
from unexpected_runtime.subagents import SubagentError


class SubagentDelegationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.provider = DeterministicMockProvider()
        self.coordinator = Coordinator(
            manifest_path=Path(__file__).resolve().parents[1] / "agent_manifest.json",
            state_dir=Path(self.temp.name) / "state",
            provider=self.provider,
            max_retries=0,
        )
        parent = self.coordinator.invoke(
            "orchestrator", "Coordinate a bounded review.",
            inputs={"request_label": "parent-only-context"},
            idempotency_key="subagent-parent-" + str(id(self)),
        )
        self.parent_task_id = parent.task_id
        self.parent_output = parent.output

    def tearDown(self):
        self.coordinator.close()
        self.temp.cleanup()

    def test_child_runs_have_isolated_context_and_persist_parent_lineage(self):
        result = self.coordinator.run_subagents(
            parent_task_id=self.parent_task_id,
            parent_agent_id="orchestrator",
            children=[
                {"agent_id": "project-manager", "objective": "Create a small project plan.",
                 "inputs": {"child_label": "planning-only"}},
                {"agent_id": "research-scout", "objective": "Research the supplied question.",
                 "inputs": {"child_label": "research-only"}},
            ],
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["children"]), 2)
        child_ids = [item["task_id"] for item in result["children"]]
        self.assertEqual(len(set(child_ids)), 2)
        tasks = {item["task_id"]: item for item in self.coordinator.store.list_tasks(100)}
        for child_id in child_ids:
            self.assertEqual(tasks[child_id]["parent_task_id"], self.parent_task_id)
        provider_payloads = [json.loads(request["user_prompt"]) for request in self.provider.requests[1:]]
        self.assertIn("planning-only", json.dumps(provider_payloads[0]))
        self.assertNotIn("research-only", json.dumps(provider_payloads[0]))
        self.assertNotIn("parent-only-context", json.dumps(provider_payloads))
        events = self.coordinator.store.events(100)
        self.assertIn("subagent_child_completed", {event["event_type"] for event in events})

    def test_handoff_scope_is_checked_before_any_child_task_is_created(self):
        before = len(self.coordinator.store.list_tasks(100))
        with self.assertRaises(PermissionDenied):
            self.coordinator.run_subagents(
                parent_task_id=self.parent_task_id,
                parent_agent_id="orchestrator",
                children=[{"agent_id": "maintenance-engineer", "objective": "Outside handoff scope."}],
            )
        self.assertEqual(len(self.coordinator.store.list_tasks(100)), before)

    def test_child_count_and_depth_budgets_fail_closed(self):
        with self.assertRaises(ValueError):
            self.coordinator.run_subagents(
                parent_task_id=self.parent_task_id,
                parent_agent_id="orchestrator",
                children=[{"agent_id": "project-manager", "objective": "Child"}] * 4,
            )
        child = self.coordinator.run_subagents(
            parent_task_id=self.parent_task_id,
            parent_agent_id="orchestrator",
            children=[{"agent_id": "code-reviewer", "objective": "Review the parent result."}],
            max_depth=1,
        )
        child_id = child["children"][0]["task_id"]
        with self.assertRaises(SubagentError):
            self.coordinator.run_subagents(
                parent_task_id=child_id,
                parent_agent_id="code-reviewer",
                children=[{"agent_id": "security-reviewer", "objective": "Review the child result."}],
                max_depth=1,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
