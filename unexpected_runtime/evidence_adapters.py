from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from .source_retrieval import SourceEvidenceChecker, SourceRetrievalError, source_retriever_from_env
from .test_execution import TestEvidenceChecker, TestExecutionConfigurationError, test_executor_from_env


def evidence_adapters_from_env(
    workspace_root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Build explicitly configured host evidence adapters and safe status labels.

    Incomplete configuration is visible but never represented as an enabled
    checker. The caller may still construct a local runtime; required checks
    remain unverified and therefore fail closed at the delivery gate.
    """
    checkers: dict[str, Any] = {}
    status = {
        "test_backend": "not configured",
        "source_backend": "not configured",
    }

    requested_test = os.getenv("UNEXPECTED_TEST_EXECUTOR", "").strip().lower()
    if requested_test:
        try:
            executor = test_executor_from_env(workspace_root)
            if executor is not None and requested_test == "render-sandbox":
                if importlib.util.find_spec("render") is None:
                    raise TestExecutionConfigurationError("The pinned Render Python SDK is not installed.")
            if executor is None:
                status["test_backend"] = "not configured"
            else:
                checkers["test"] = TestEvidenceChecker(executor)
                status["test_backend"] = (
                    "enabled: docker" if requested_test == "docker"
                    else "enabled: render-sandbox"
                )
        except (TestExecutionConfigurationError, OSError, ValueError) as exc:
            status["test_backend"] = f"blocked: {type(exc).__name__}"

    requested_domains = os.getenv("UNEXPECTED_SOURCE_ALLOWED_DOMAINS", "").strip()
    if requested_domains:
        try:
            retriever = source_retriever_from_env()
            if retriever is None:
                status["source_backend"] = "not configured"
            else:
                checkers["source"] = SourceEvidenceChecker(retriever)
                status["source_backend"] = "enabled: allowlisted-https"
        except (SourceRetrievalError, OSError, ValueError) as exc:
            status["source_backend"] = f"blocked: {type(exc).__name__}"

    return checkers, status
