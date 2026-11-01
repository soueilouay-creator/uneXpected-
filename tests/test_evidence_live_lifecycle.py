from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unexpected_runtime.coordinator import Coordinator


ROOT = Path(__file__).resolve().parents[1]
LIVE_FLAG = "UNEXPECTED_RUN_LIVE_EVIDENCE_INTEGRATION"


class EvidenceLifecycleTaskProvider:
    """Scripted lifecycle participant; external retrieval and test execution are real."""

    name = "evidence-lifecycle-test-provider"
    configured = True
    retry_safe = False

    def __init__(self) -> None:
        self.review_calls = 0
        self.worker_calls = 0

    @staticmethod
    def _payload(user_prompt: str) -> dict:
        return json.loads(user_prompt)

    def generate(self, *, system_prompt: str, user_prompt: str,
                 agent_id: str, task_id: str, timeout: float) -> str:
        payload = self._payload(user_prompt)
        inputs = payload.get("inputs", {})

        if agent_id == "project-manager":
            request = inputs["request"]
            self.assert_request_has_source(request)
            return json.dumps({
                "steps": [
                    "Retrieve the official Python unittest documentation",
                    "Run the fixed evidence-engine regression profile in an isolated test sandbox",
                    "Write a short, sourced explanation of unittest test discovery",
                ],
                "acceptance_criteria": [
                    {
                        "id": "ARTIFACT-01",
                        "description": "Deliverable is non-empty",
                        "kind": "artifact",
                        "target": "A readable explanation of unittest test discovery",
                        "required": True,
                    },
                    {
                        "id": "TEST-01",
                        "description": "Evidence engine regression profile passes in an isolated sandbox",
                        "kind": "test",
                        "profile": "evidence-engine",
                        "target": "All tests in the evidence-engine profile pass; exit code 0",
                        "required": True,
                    },
                    {
                        "id": "SOURCE-01",
                        "description": "Official Python documentation is retrieved for independent review",
                        "kind": "source",
                        "target": "Retrieve the official unittest documentation with title, excerpt and SHA-256 provenance",
                        "required": True,
                    },
                ],
            })

        if agent_id == "research-scout":
            self.worker_calls += 1
            if "candidate" in inputs:
                return (
                    "Improved explanation: Python's unittest framework supports test discovery, "
                    "so a project can locate and run matching tests without listing each test module "
                    "individually. The official Python unittest documentation describes discovery "
                    "and its command-line interface."
                )
            return (
                "Python's unittest framework supports test discovery, allowing a project to locate "
                "and run matching tests without listing every test module. The official Python "
                "unittest documentation describes the discovery process and command-line interface."
            )

        if agent_id == "code-reviewer":
            self.review_calls += 1
            evidence = inputs.get("evidence_report", {})
            report_items = evidence.get("evidence", [])
            artifact = next((item for item in report_items if item.get("kind") == "artifact"), None)
            test = next((item for item in report_items if item.get("kind") == "test"), None)
            source = next((item for item in report_items if item.get("kind") == "source"), None)

            test_actual = test.get("actual", {}) if isinstance(test, dict) else {}
            source_actual = source.get("actual", {}) if isinstance(source, dict) else {}
            sources = source_actual.get("sources", []) if isinstance(source_actual, dict) else []
            excerpt = " ".join(
                [str(item.get("title", "")) + " " + str(item.get("excerpt", "")) for item in sources]
            ).lower()
            candidate = str(inputs.get("candidate", "")).lower()
            valid = (
                "unittest" in candidate and "discovery" in candidate
                and evidence.get("passed") is True
                and isinstance(artifact, dict) and artifact.get("status") == "passed"
                and isinstance(test, dict) and test.get("status") == "passed"
                and test_actual.get("exit_code") == 0
                and isinstance(test_actual.get("tests_run"), int) and test_actual["tests_run"] > 0
                and test_actual.get("cleanup_confirmed") is True
                and isinstance(source, dict) and source.get("status") == "passed"
                and source_actual.get("source_count") == 1
                and sources and sources[0].get("domain") == "docs.python.org"
                and sources[0].get("sha256")
                and ("discovery" in excerpt or "discover" in excerpt)
            )
            if not valid:
                return (
                    "VERDICT: FAIL\n"
                    "Required evidence is missing, unverified, or not relevant to the task. "
                    "Check ARTIFACT-01, TEST-01 and SOURCE-01 before delivery."
                )
            return (
                "VERDICT: PASS\n"
                "ARTIFACT-01: candidate is present. "
                "TEST-01: the isolated profile reported a zero exit code, a non-zero test count "
                "and confirmed cleanup. "
                "SOURCE-01: the official docs.python.org unittest page was retrieved and its "
                "title/excerpt contains test-discovery material. "
                "The retrieved source and test report are bound to this candidate's evidence record."
            )

        return "Unrecognized stage role; no task result was produced."

    @staticmethod
    def assert_request_has_source(request: dict) -> None:
        inputs = request.get("inputs", {})
        if not isinstance(inputs.get("source_refs"), list) or not inputs["source_refs"]:
            raise ValueError("The lifecycle task must supply official source references.")


@unittest.skipUnless(
    os.getenv(LIVE_FLAG) == "1",
    "Set UNEXPECTED_RUN_LIVE_EVIDENCE_INTEGRATION=1 to run the real source + isolated sandbox lifecycle.",
)
class LiveEvidenceLifecycleTests(unittest.TestCase):
    def test_unittest_discovery_task_requires_real_source_and_isolated_test_evidence(self):
        image = os.getenv("UNEXPECTED_TEST_DOCKER_IMAGE", "")
        self.assertRegex(image, r"^\S+@sha256:[0-9a-f]{64}$")
        self.assertEqual(os.getenv("UNEXPECTED_TEST_EXECUTOR"), "docker")
        self.assertEqual(os.getenv("UNEXPECTED_SOURCE_ALLOWED_DOMAINS"), "docs.python.org")

        provider = EvidenceLifecycleTaskProvider()
        reviewer_provider = EvidenceLifecycleTaskProvider()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = {
            "UNEXPECTED_TEST_EXECUTOR": "docker",
            "UNEXPECTED_TEST_DOCKER_IMAGE": image,
            "UNEXPECTED_TEST_WORKSPACE_ROOT": str(ROOT),
            "UNEXPECTED_TEST_TIMEOUT_SECONDS": "180",
            "UNEXPECTED_SOURCE_ALLOWED_DOMAINS": "docs.python.org",
            "UNEXPECTED_SOURCE_TIMEOUT_SECONDS": "10",
            "UNEXPECTED_SOURCE_MAX_BYTES": "524288",
            "UNEXPECTED_SOURCE_MAX_COUNT": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            coordinator = Coordinator(
                manifest_path=ROOT / "agent_manifest.json",
                state_dir=temp.name,
                provider=provider,
                reviewer_provider=reviewer_provider,
                max_workers=2,
                max_retries=0,
            )
        self.addCleanup(coordinator.close)

        status = coordinator.status()
        self.assertEqual(status["test_backend"], "enabled: docker")
        self.assertEqual(status["source_backend"], "enabled: allowlisted-https")
        self.assertIn("test", status["evidence_checkers"])
        self.assertIn("source", status["evidence_checkers"])

        with patch.dict(os.environ, env, clear=False):
            result = coordinator.run_lifecycle(
                "research-scout",
                "Explain Python unittest test discovery using the official Python documentation "
                "and verify the evidence-engine regression profile in an isolated test sandbox.",
                {
                    "source_refs": [
                        "https://docs.python.org/3/library/unittest.html",
                    ],
                },
                max_corrections=0,
                max_improvements=2,
                deadline_seconds=60,
            )

        self.assertEqual(result.status, "delivered", result.error)
        self.assertTrue(result.delivered)
        self.assertEqual(reviewer_provider.review_calls, 2)
        self.assertIsNot(provider, reviewer_provider)
        self.assertEqual(provider.worker_calls, 2)
        self.assertEqual(len(result.evidence_history), 2)
        self.assertEqual(
            [entry["passed"] for entry in result.verification_history],
            [True, True],
        )
        self.assertNotEqual(
            result.evidence_history[0]["candidate_sha256"],
            result.evidence_history[1]["candidate_sha256"],
        )
        for report in result.evidence_history:
            self.assertTrue(report["passed"])
            evidence_by_kind = {entry["kind"]: entry for entry in report["evidence"]}
            self.assertEqual(evidence_by_kind["test"]["status"], "passed")
            self.assertEqual(evidence_by_kind["test"]["actual"]["exit_code"], 0)
            self.assertGreater(evidence_by_kind["test"]["actual"]["tests_run"], 0)
            self.assertTrue(evidence_by_kind["test"]["actual"]["cleanup_confirmed"])
            self.assertEqual(evidence_by_kind["source"]["status"], "passed")
            source = evidence_by_kind["source"]["actual"]["sources"][0]
            self.assertEqual(source["domain"], "docs.python.org")
            self.assertEqual(len(source["sha256"]), 64)

        events = {event["event_type"] for event in coordinator.store.events(200)}
        self.assertIn("outcome_recorded", events)
        self.assertIn("workflow_cycle_learned", events)


if __name__ == "__main__":
    unittest.main(verbosity=2)
