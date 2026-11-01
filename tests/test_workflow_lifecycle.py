import unittest

from unexpected_runtime.workflow import WorkflowRunner


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
        self.assertEqual(events, ["plan", "execute", "verify", "improve", "deliver", "learn"])
        self.assertTrue(result.delivered)
        self.assertEqual(result.delivery, {"artifact": "draft-improved"})
        self.assertEqual(result.status, "delivered")

    def test_failed_verification_replans_before_retry_and_never_delivers_failed_output(self):
        events = []
        checks = iter([
            {"passed": False, "feedback": "missing source evidence"},
            {"passed": True, "feedback": ""},
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
