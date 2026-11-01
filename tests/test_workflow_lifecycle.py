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
        self.assertEqual(result.verified_output, "verified-draft-fixed")
        self.assertEqual(result.delivery, "verified-draft-fixed")
        self.assertEqual(events.count("deliver"), 1)
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
                    return f"VERDICT: {verdict}" + chr(10) + f"Review evidence for {verdict.lower()}."
                if agent == "research-scout":
                    return "Research deliverable, version " + str(self.review_calls)
                return "Test response."

        temp = tempfile.TemporaryDirectory()
        provider = LifecycleProvider()
        coordinator = Coordinator(manifest_path=Path(__file__).resolve().parents[1] / "agent_manifest.json",
                                  state_dir=temp.name, provider=provider)
        self.addCleanup(temp.cleanup)
        self.addCleanup(coordinator.close)
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
        self.assertIsNone(result.verified_output)
        events = {event["event_type"] for event in coordinator.store.events(100)}
        self.assertIn("outcome_recorded", events)

    def test_authenticated_http_lifecycle_endpoint_uses_native_workflow(self):
        import json
        import threading
        import urllib.request
        from unexpected_runtime.http_api import create_server

        coordinator, provider = self._coordinator(["PASS", "PASS"])
        token = "t" * 40
        server = create_server(coordinator=coordinator, api_token=token, host="127.0.0.1", port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = "http://127.0.0.1:{}/v1/lifecycle".format(server.server_address[1])
            body = json.dumps({
                "agent_id": "research-scout",
                "objective": "Run a safe test workflow",
                "inputs": {"scope": "fixture"},
                "max_corrections": 0,
                "deadline_seconds": 5,
            }).encode("utf-8")
            request = urllib.request.Request(
                url, data=body,
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
                self.assertEqual(response.status, 200)
                self.assertEqual(payload["result"]["status"], "delivered")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_lifecycle_concurrency_guard_preserves_capacity_for_invoke(self):
        import json
        import threading
        import urllib.error
        import urllib.request
        from unexpected_runtime.http_api import create_server

        class Result:
            def __init__(self, status):
                self.status = status
            def to_dict(self):
                return {"status": self.status, "delivered": self.status == "delivered"}

        class BlockingCoordinator:
            max_workers = 2
            def __init__(self):
                self.started = threading.Event()
                self.release = threading.Event()
            def run_lifecycle(self, *args, **kwargs):
                if self.started.is_set():
                    return Result("delivered")
                self.started.set()
                self.release.wait(timeout=5)
                return Result("delivered")
            def invoke(self, *args, **kwargs):
                return Result("completed")

        coordinator = BlockingCoordinator()
        token = "c" * 40
        server = create_server(coordinator=coordinator, api_token=token,
                               host="127.0.0.1", port=0)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        base_url = "http://127.0.0.1:{}".format(server.server_address[1])

        def post(route):
            payload = {
                "agent_id": "research-scout",
                "objective": "Exercise the worker-capacity guard",
                "inputs": {},
                "deadline_seconds": 5,
            }
            if route == "/v1/lifecycle":
                payload["max_corrections"] = 0
            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                base_url + route, data=body,
                headers={"Authorization": "Bearer " + token,
                         "Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=3) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                return exc.code, json.loads(exc.read().decode("utf-8"))

        first_result = []
        lifecycle_thread = threading.Thread(
            target=lambda: first_result.append(post("/v1/lifecycle")), daemon=True
        )
        lifecycle_thread.start()
        try:
            self.assertTrue(coordinator.started.wait(timeout=2))
            busy_status, busy_payload = post("/v1/lifecycle")
            self.assertEqual(busy_status, 503, busy_payload)
            invoke_status, invoke_payload = post("/v1/invoke")
            self.assertEqual(invoke_status, 200, invoke_payload)
        finally:
            coordinator.release.set()
            lifecycle_thread.join(timeout=4)
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=2)

        self.assertEqual(len(first_result), 1)
        self.assertEqual(first_result[0][0], 200)

    def test_default_deterministic_mock_cannot_pass_verification_gate(self):
        import tempfile
        from pathlib import Path
        from unexpected_runtime.coordinator import Coordinator
        from unexpected_runtime.providers import DeterministicMockProvider

        with tempfile.TemporaryDirectory() as state:
            coordinator = Coordinator(
                manifest_path=Path(__file__).resolve().parents[1] / "agent_manifest.json",
                state_dir=state, provider=DeterministicMockProvider(),
            )
            try:
                result = coordinator.run_lifecycle(
                    "research-scout", "Research a test topic", {"scope": "fixture"},
                    max_corrections=0,
                )
                self.assertEqual(result.status, "blocked_verification")
                self.assertFalse(result.delivered)
                self.assertIsNone(result.delivery)
                self.assertFalse(result.verification_history[0]["passed"])
            finally:
                coordinator.close()


if __name__ == "__main__":
    unittest.main()
