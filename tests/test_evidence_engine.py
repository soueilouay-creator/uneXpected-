import unittest

from unexpected_runtime.evidence import EvidenceContractError, EvidenceEngine


class EvidenceEngineTests(unittest.TestCase):
    def test_missing_executor_for_required_test_and_source_checks_blocks(self):
        engine = EvidenceEngine()
        criteria = [
            {"id": "TEST-01", "description": "Regression tests pass", "kind": "test", "target": "0 failures", "required": True},
            {"id": "SOURCE-01", "description": "Claims are traceable", "kind": "source", "target": "Every factual claim has a source", "required": True},
        ]

        report = engine.evaluate("candidate", criteria)

        self.assertFalse(report["passed"])
        self.assertEqual([item["status"] for item in report["evidence"]], ["unverified", "unverified"])
        self.assertEqual(report["failed_criteria"], ["TEST-01", "SOURCE-01"])

    def test_registered_checkers_must_return_measured_evidence(self):
        def checker(candidate, criterion, context):
            return {
                "passed": True,
                "actual": "0 failures",
                "expected": criterion["target"],
                "evidence_ref": "ci://run/123",
                "details": "Executed the required regression suite.",
            }

        engine = EvidenceEngine(checkers={"test": checker})
        criteria = [{"id": "TEST-01", "description": "Regression tests pass", "kind": "test",
                     "target": "0 failures", "required": True}]

        report = engine.evaluate("candidate", criteria)

        self.assertTrue(report["passed"])
        self.assertEqual(report["evidence"][0]["status"], "passed")
        self.assertEqual(report["evidence"][0]["evidence_ref"], "ci://run/123")
        self.assertTrue(engine.is_current(report, "candidate"))
        self.assertFalse(engine.is_current(report, "modified candidate"))

    def test_checker_cannot_report_pass_without_provenance(self):
        engine = EvidenceEngine(checkers={
            "source": lambda candidate, criterion, context: {
                "passed": True, "actual": "looks good", "expected": criterion["target"],
            }
        })
        criteria = [{"id": "SOURCE-01", "description": "Verify source content", "kind": "source",
                     "target": "Source supports claim", "required": True}]

        report = engine.evaluate("candidate", criteria)

        self.assertFalse(report["passed"])
        self.assertEqual(report["evidence"][0]["status"], "unverified")
        self.assertIn("evidence_ref", report["evidence"][0]["missing_fields"])

    def test_optional_unverified_criterion_does_not_override_required_pass(self):
        engine = EvidenceEngine(checkers={
            "artifact": lambda candidate, criterion, context: {
                "passed": True, "actual": "non-empty", "expected": "non-empty",
                "evidence_ref": "runtime://candidate",
            }
        })
        criteria = [
            {"id": "ARTIFACT-01", "description": "Deliverable exists", "kind": "artifact",
             "target": "non-empty", "required": True},
            {"id": "TEST-01", "description": "Optional test evidence", "kind": "test",
             "target": "0 failures", "required": False},
        ]

        report = engine.evaluate("candidate", criteria)

        self.assertTrue(report["passed"])
        self.assertEqual(report["evidence"][1]["status"], "unverified")
        self.assertEqual(report["failed_criteria"], [])

    def test_duplicate_or_invalid_criteria_are_rejected(self):
        engine = EvidenceEngine()
        duplicate = [
            {"id": "A", "description": "First", "kind": "artifact", "target": "x", "required": True},
            {"id": "A", "description": "Second", "kind": "artifact", "target": "x", "required": True},
        ]
        with self.assertRaises(EvidenceContractError):
            engine.evaluate("candidate", duplicate)
        with self.assertRaises(EvidenceContractError):
            engine.evaluate("candidate", [])

    def test_workflow_runner_rejects_stale_evidence_even_when_reviewer_passes(self):
        from unexpected_runtime.workflow import WorkflowRunner

        engine = EvidenceEngine()
        criteria = [{"id": "ARTIFACT-01", "description": "Deliverable exists", "kind": "artifact",
                     "target": "non-empty text", "required": True}]
        stale_report = engine.evaluate("a different candidate", criteria)
        runner = WorkflowRunner(
            plan=lambda request, feedback=None: {},
            execute=lambda plan: "current candidate",
            verify=lambda candidate, plan: {
                "passed": True, "feedback": "VERDICT: PASS",
                "evidence_report": stale_report,
            },
            improve=lambda candidate, feedback: self.fail("stale evidence must not reach improvement"),
            deliver=lambda candidate: self.fail("stale evidence must never be delivered"),
            learn=lambda record: None,
            max_corrections=0,
            evidence_required=True,
        )

        result = runner.run({"objective": "verify candidate binding"})

        self.assertEqual(result.status, "blocked_verification")
        self.assertFalse(result.delivered)
        self.assertEqual(len(result.evidence_history), 1)
        self.assertIn("Evidence gate blocked delivery", result.error)

    def test_checker_failure_and_exception_fail_closed(self):
        def raising_checker(candidate, criterion, context):
            raise RuntimeError("private checker details")

        engine = EvidenceEngine(checkers={"test": raising_checker})
        criteria = [{"id": "TEST-01", "description": "Run tests", "kind": "test",
                     "target": "0 failures", "required": True}]

        report = engine.evaluate("candidate", criteria)

        self.assertFalse(report["passed"])
        self.assertEqual(report["evidence"][0]["status"], "failed")
        self.assertIn("RuntimeError", report["evidence"][0]["details"])
        self.assertNotIn("private checker details", report["evidence"][0]["details"])


if __name__ == "__main__":
    unittest.main()
