import asyncio
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from unexpected_runtime.test_execution import (
    DockerTestExecutor,
    RenderSandboxTestExecutor,
    TestExecutionConfigurationError,
    TestEvidenceChecker,
    test_executor_from_env,
)


FILES = (
    "tests/test_evidence_engine.py",
    "unexpected_runtime/__init__.py",
    "unexpected_runtime/evidence.py",
    "unexpected_runtime/workflow.py",
)
PASS_OUTPUT = "test_one ... ok\nRan 1 test in 0.01s\n\nOK\n"


def make_workspace():
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    source_root = Path(__file__).resolve().parents[1]
    for relative in FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative == "tests/test_evidence_engine.py":
            shutil.copyfile(source_root / relative, path)
        else:
            path.write_text("fixture", encoding="utf-8")
    return temp, root


class DockerTestExecutorTests(unittest.TestCase):
    def test_requires_immutable_image_digest(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        with self.assertRaises(TestExecutionConfigurationError):
            DockerTestExecutor(root, image_digest="python:3.12-slim")

    def test_modified_test_profile_is_rejected_before_container_execution(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        (root / "tests/test_evidence_engine.py").write_text(
            "print('Ran 1 test in 0.01s\\nOK')", encoding="utf-8"
        )
        executor = DockerTestExecutor(
            root,
            image_digest="python:3.12-slim@sha256:" + "d" * 64,
            docker_binary="/usr/bin/docker",
        )
        with patch("unexpected_runtime.test_execution.subprocess.run") as run:
            with self.assertRaises(TestExecutionConfigurationError):
                executor("candidate", {"profile": "evidence-engine"}, {})
        run.assert_not_called()

    def test_non_python_image_family_is_rejected_even_with_a_digest(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        with self.assertRaises(TestExecutionConfigurationError):
            DockerTestExecutor(root, image_digest="evil/python:latest@sha256:" + "e" * 64)

    def test_runs_only_fixed_profile_in_strict_offline_container(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        image = "python:3.12-slim-trixie@sha256:" + "a" * 64
        completed = subprocess.CompletedProcess(
            args=["docker"], returncode=0, stdout=PASS_OUTPUT, stderr="",
        )
        with patch("unexpected_runtime.test_execution.shutil.which", return_value="/usr/bin/docker"), \
             patch("unexpected_runtime.test_execution.subprocess.run", return_value=completed) as run:
            executor = DockerTestExecutor(root, image_digest=image)
            result = executor("candidate", {"profile": "evidence-engine"}, {})
        self.assertTrue(result["passed"])
        self.assertEqual(result["actual"]["tests_run"], 1)
        argv = run.call_args_list[0].args[0]
        self.assertIn("--network=none", argv)
        self.assertIn("--read-only", argv)
        self.assertIn("--cap-drop=ALL", argv)
        self.assertIn("--security-opt=no-new-privileges", argv)
        self.assertIn("--pids-limit=64", argv)
        self.assertIn("--memory=256m", argv)
        self.assertIn("--cpus=1", argv)
        self.assertIn("--user=65532:65532", argv)
        self.assertEqual(run.call_args_list[0].kwargs["shell"], False)
        self.assertIn("test_evidence_engine.py", argv)
        self.assertNotIn("candidate", " ".join(argv))

    def test_rejects_unknown_profiles_and_missing_files(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        executor = DockerTestExecutor(root, image_digest="python:3.12-slim@sha256:" + "b" * 64,
                                      docker_binary="/usr/bin/docker")
        with self.assertRaises(TestExecutionConfigurationError):
            executor("candidate", {"profile": "run-arbitrary-shell"}, {})
        (root / "tests/test_evidence_engine.py").unlink()
        with self.assertRaises(TestExecutionConfigurationError):
            executor("candidate", {"profile": "evidence-engine"}, {})

    def test_nonzero_exit_and_timeout_are_never_reported_as_pass(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        executor = DockerTestExecutor(root, image_digest="python:3.12-slim@sha256:" + "c" * 64,
                                      docker_binary="/usr/bin/docker")
        failed = subprocess.CompletedProcess(args=["docker"], returncode=1,
                                              stdout="Ran 1 test in 0.01s\n\nFAILED (failures=1)\n",
                                              stderr="")
        with patch("unexpected_runtime.test_execution.subprocess.run", return_value=failed):
            result = executor("candidate", {"profile": "evidence-engine"}, {})
        self.assertFalse(result["passed"])
        self.assertEqual(result["actual"]["exit_code"], 1)
        with patch("unexpected_runtime.test_execution.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["docker"], 1)):
            timed_out = executor("candidate", {"profile": "evidence-engine"}, {})
        self.assertFalse(timed_out["passed"])
        self.assertEqual(timed_out["actual"]["status"], "timeout")


class FakeSandbox:
    def __init__(self, *, cleanup_fails=False):
        self.calls = []
        self.cleanup_fails = cleanup_fails

    async def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return SimpleNamespace(id="sbx-test-123")

    async def wait_until_running(self, sandbox_id, **kwargs):
        self.calls.append(("wait", sandbox_id, kwargs))
        return SimpleNamespace(id=sandbox_id, status="running")

    async def copy_to(self, sandbox_id, local_path, remote_path):
        staged_root = Path(local_path)
        self.copied_files = sorted(
            item.relative_to(staged_root).as_posix()
            for item in staged_root.rglob("*")
            if item.is_file()
        )
        self.calls.append(("copy", sandbox_id, staged_root, remote_path))

    async def exec(self, sandbox_id, command):
        self.calls.append(("exec", sandbox_id, command))
        async def events():
            yield SimpleNamespace(stream="stdout", data=PASS_OUTPUT)
            yield SimpleNamespace(exit_code=0)
        return_iter = events()
        async for event in return_iter:
            yield event

    async def terminate(self, sandbox_id):
        self.calls.append(("terminate", sandbox_id))
        if self.cleanup_fails:
            raise RuntimeError("cleanup unavailable")


class RenderSandboxTestExecutorTests(unittest.TestCase):
    def test_uses_deny_all_microvm_and_cleans_up(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        sandbox_api = FakeSandbox()
        executor = RenderSandboxTestExecutor(
            workspace_root=root, workspace_id="workspace-test", token="secret-token",
            sandboxes=sandbox_api,
        )

        result = executor("candidate", {"profile": "evidence-engine"}, {})

        self.assertTrue(result["passed"])
        self.assertEqual(result["actual"]["sandbox_id"], "sbx-test-123")
        create = next(call for call in sandbox_api.calls if call[0] == "create")
        self.assertEqual(create[1]["network_policy"], "deny-all")
        self.assertNotIn("env", create[1])
        self.assertIn("python3 -m unittest discover", next(call[2] for call in sandbox_api.calls if call[0] == "exec"))
        self.assertEqual([call[0] for call in sandbox_api.calls],
                         ["create", "wait", "copy", "exec", "terminate"])
        self.assertEqual(sandbox_api.copied_files, sorted(FILES))

    def test_cleanup_failure_blocks_even_a_passing_test_result(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        executor = RenderSandboxTestExecutor(
            workspace_root=root, workspace_id="workspace-test", token="secret-token",
            sandboxes=FakeSandbox(cleanup_fails=True),
        )
        result = executor("candidate", {"profile": "evidence-engine"}, {})
        self.assertFalse(result["passed"])
        self.assertFalse(result["actual"]["cleanup_confirmed"])

    def test_invalid_profile_does_not_create_remote_sandbox(self):
        temp, root = make_workspace()
        self.addCleanup(temp.cleanup)
        sandbox_api = FakeSandbox()
        executor = RenderSandboxTestExecutor(
            workspace_root=root, workspace_id="workspace-test", token="secret-token",
            sandboxes=sandbox_api,
        )
        with self.assertRaises(TestExecutionConfigurationError):
            executor("candidate", {"profile": "../etc/passwd"}, {})
        self.assertEqual(sandbox_api.calls, [])


class TestExecutorFactoryTests(unittest.TestCase):
    def test_no_backend_is_not_registered_by_default(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(test_executor_from_env())

    def test_render_backend_requires_host_credentials(self):
        env = {
            "UNEXPECTED_TEST_EXECUTOR": "render-sandbox",
            "RENDER_WORKSPACE_ID": "workspace-test",
        }
        with patch.dict("os.environ", env, clear=True):
            with self.assertRaises(TestExecutionConfigurationError):
                test_executor_from_env()

    def test_evidence_checker_requires_pass_with_exit_and_test_count(self):
        class Executor:
            def __call__(self, candidate, criterion, context):
                return {
                    "passed": False,
                    "actual": {"exit_code": 0, "tests_run": 0},
                    "evidence_ref": "sandbox://test",
                    "details": "No unittest result summary was present.",
                }

        checker = TestEvidenceChecker(Executor())
        result = checker("candidate", {"id": "TEST-01", "target": "all tests pass"},
                         {"source_refs": []})
        self.assertFalse(result["passed"])
        self.assertEqual(result["actual"]["tests_run"], 0)
        self.assertEqual(result["evidence_ref"], "sandbox://test")


if __name__ == "__main__":
    unittest.main()
