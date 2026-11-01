import unittest
import tempfile
from pathlib import Path

from unexpected_runtime.workflow import WorkflowRunner
from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.providers import DeterministicMockProvider

ROOT = Path(__file__).resolve().parents[1]


class WorkflowRunnerTests(unittest.TestCase):
    def test_delivers_only_after_verify_and_improve(self):
        events = []
        runner = WorkflowRunner(
            plan=lambda request, feedback=None: events.append("plan") or {"steps": ["work"]},
            execute=lambda plan: events.append("execute") or "draft",
            verify=lambda result, plan: events.append("verify") or {"passed": True, "feedback": ""},
            improve=lambda result, feedback: events.append("improve") or result + "-improved",
            deliver=lambda result: events.append("deliver") or {"artifact": result},
            learn=lambda record: events.append("learn"),
        )
        result = runner.run({"objective": "make a report"})
        self.assertEqual(events, ["plan", "execute", "verify", "improve", "verify", "deliver", "learn"])
        self.assertTrue(result.delivered)
        self.assertEqual(result.delivery, {"artifact": "draft-improved"})
        self.assertEqual(result.status, "delivered")

    def test_failed_verification_replans_before_retry_and_never_delivers_failed_output(self):
        events = []
        checks = iter([
            {"passed": False, "feedback": "missing source evidence"},
            {"passed": True, "feedback": ""},
            {"passed": True, "feedback": "final output is ready"},
        ])
        def plan(request, feedback=None):
            events.append(("plan", feedback))
            return {"feedback": feedback}
        runner = WorkflowRunner(
            plan=plan,
            execute=lambda plan: events.append("execute") or "verified-draft",
            verify=lambda result, plan: events.append("verify") or next(checks),
            improve=lambda result, feedback: events.append("improve") or result + "-fixed",
            deliver=lambda result: events.append("deliver") or result,
            learn=lambda record: events.append("learn"),
            max_corrections=1,
        )
        result = runner.run({"objective": "research"})
        self.assertEqual(result.status, "delivered")
        self.assertEqual(events[0], ("plan", None))
        self.assertEqual(events[3], ("plan", "missing source evidence"))
        self.assertNotIn(("deliver", "verified-draft"), events)
        self.assertEqual(result.corrections, 1)

    def test_exhausted_verification_blocks_delivery_but_still_learns(self):
        events = []
        runner = WorkflowRunner(
            plan=lambda request, feedback=None: {},
            execute=lambda plan: "draft",
            verify=lambda result, plan: {"passed": False, "feedback": "not ready"},
            improve=lambda result, feedback: self.fail("must not improve unverified output"),
            deliver=lambda result: self.fail("must not deliver unverified output"),
            learn=lambda record: events.append(record),
            max_corrections=0,
        )
        result = runner.run({"objective": "unsafe task"})
        self.assertEqual(result.status, "blocked_verification")
        self.assertFalse(result.delivered)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["verification_history"][-1]["passed"], False)


if __name__ == "__main__":
    unittest.main()


class CoordinatorLifecycleTests(unittest.TestCase):
    def _coordinator(self, reviewer_verdicts):
        import tempfile
        from pathlib import Path
        from unexpected_runtime.coordinator import Coordinator

        class LifecycleProvider:
            name = "test-lifecycle-provider"
            configured = True
            retry_safe = False
            def __init__(self):
                self.review_calls = 0
            def generate(self, **kwargs):
                agent = kwargs["agent_id"]
                if agent == "project-manager":
                    return "1. Define the task. 2. Produce the requested output. 3. Review it."
                if agent == "code-reviewer":
                    verdict = reviewer_verdicts[self.review_calls]
                    self.review_calls += 1
                    return f"VERDICT: {verdict}\\nReview evidence for {verdict.lower()}."
                if agent == "research-scout":
                    return "Research deliverable, version " + str(self.review_calls)
                return "Test response."

        temp = tempfile.TemporaryDirectory()
        provider = LifecycleProvider()
        coordinator = Coordinator(manifest_path=Path(__file__).resolve().parents[1] / "agent_manifest.json",
                                  state_dir=temp.name, provider=provider)
        self.addCleanup(coordinator.close)
        self.addCleanup(temp.cleanup)
        return coordinator, provider

    def test_native_lifecycle_routes_through_plan_execute_review_improve_and_learning(self):
        coordinator, provider = self._coordinator(["PASS", "PASS"])
        result = coordinator.run_lifecycle(
            "research-scout", "Research a sample topic", {"scope": "public sources"},
            max_corrections=0,
        )
        self.assertEqual(result.status, "delivered")
        self.assertTrue(result.delivered)
        self.assertEqual(provider.review_calls, 2)
        self.assertEqual([item["phase"] for item in result.verification_history],
                         ["before_improvement", "after_improvement"])
        events = {event["event_type"] for event in coordinator.store.events(100)}
        self.assertIn("outcome_recorded", events)

    def test_native_lifecycle_blocks_delivery_when_improvement_fails_final_review(self):
        coordinator, provider = self._coordinator(["PASS", "FAIL"])
        result = coordinator.run_lifecycle(
            "research-scout", "Research a sample topic", {"scope": "public sources"},
            max_corrections=0,
        )
        self.assertEqual(result.status, "blocked_verification")
        self.assertFalse(result.delivered)
        self.assertEqual(provider.review_calls, 2)
        self.assertIsNone(result.delivery)
        events = {event["event_type"] for event in coordinator.store.events(100)}
        self.assertIn("outcome_recorded", events)
