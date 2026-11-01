import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unexpected_runtime.evidence_adapters import evidence_adapters_from_env


class EvidenceAdapterConfigurationTests(unittest.TestCase):
    def test_empty_environment_has_no_external_checkers(self):
        with patch.dict("os.environ", {}, clear=True):
            checkers, status = evidence_adapters_from_env()
        self.assertEqual(checkers, {})
        self.assertEqual(status, {
            "test_backend": "not configured",
            "source_backend": "not configured",
        })

    def test_docker_and_allowlisted_source_adapters_register_without_executing(self):
        image = "python:3.12-slim-bookworm@sha256:" + "a" * 64
        env = {
            "UNEXPECTED_TEST_EXECUTOR": "docker",
            "UNEXPECTED_TEST_DOCKER_IMAGE": image,
            "UNEXPECTED_TEST_TIMEOUT_SECONDS": "180",
            "UNEXPECTED_SOURCE_ALLOWED_DOMAINS": "docs.python.org",
            "UNEXPECTED_SOURCE_TIMEOUT_SECONDS": "10",
            "UNEXPECTED_SOURCE_MAX_BYTES": "524288",
            "UNEXPECTED_SOURCE_MAX_COUNT": "1",
        }
        with patch.dict("os.environ", env, clear=True), \
             patch("unexpected_runtime.test_execution.shutil.which", return_value="/usr/bin/docker"):
            checkers, status = evidence_adapters_from_env()
        self.assertEqual(set(checkers), {"test", "source"})
        self.assertEqual(status["test_backend"], "enabled: docker")
        self.assertEqual(status["source_backend"], "enabled: allowlisted-https")

    def test_incomplete_test_configuration_is_blocked_not_reported_enabled(self):
        env = {"UNEXPECTED_TEST_EXECUTOR": "docker"}
        with patch.dict("os.environ", env, clear=True):
            checkers, status = evidence_adapters_from_env()
        self.assertNotIn("test", checkers)
        self.assertTrue(status["test_backend"].startswith("blocked: TestExecutionConfigurationError"))

    def test_render_sandbox_is_blocked_when_sdk_is_missing(self):
        env = {
            "UNEXPECTED_TEST_EXECUTOR": "render-sandbox",
            "RENDER_API_KEY": "r" * 48,
            "RENDER_WORKSPACE_ID": "test-workspace",
        }
        with patch.dict("os.environ", env, clear=True), \\
             patch("importlib.util.find_spec", return_value=None):
            checkers, status = evidence_adapters_from_env()
        self.assertNotIn("test", checkers)
        self.assertEqual(status["test_backend"],
                         "blocked: TestExecutionConfigurationError")

    def test_invalid_source_allowlist_is_blocked_not_reported_enabled(self):
        env = {"UNEXPECTED_SOURCE_ALLOWED_DOMAINS": "localhost"}
        with patch.dict("os.environ", env, clear=True):
            checkers, status = evidence_adapters_from_env()
        self.assertNotIn("source", checkers)
        self.assertTrue(status["source_backend"].startswith("blocked: SourceRetrievalError"))


if __name__ == "__main__":
    unittest.main()
