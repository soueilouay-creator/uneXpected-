import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from unexpected_runtime.capabilities import CapabilityRecord, CapabilityRegistry
from unexpected_runtime.models import CancellationToken, PermissionDenied
from unexpected_runtime.permissions import PermissionPolicy
from unexpected_runtime.registry import AgentRegistry
from unexpected_runtime.storage import StateStore
from unexpected_runtime.mcp import (
    MCPToolBoundary, MCPToolError, MCPToolPermissionError, MCPToolTimeout,
    ToolCallContext, ToolDescriptor,
)


class FakeAdapter:
    def __init__(self, descriptor, value=None):
        self.descriptor = descriptor
        self.value = {"ok": True} if value is None else value
        self.calls = []

    def describe(self):
        return [self.descriptor]

    def call(self, tool_id, arguments, context):
        self.calls.append((tool_id, arguments, context.task_id))
        return self.value


class MCPBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.temp.name) / "state.sqlite3")
        self.agents = AgentRegistry.load()
        self.permissions = PermissionPolicy()
        self.source_hash = hashlib.sha256(b"verified adapter package v1").hexdigest()
        self.capabilities = CapabilityRegistry(
            self.store, adapter_verifier=lambda record: record.adapter_type == "mcp"
        )
        self.capability = CapabilityRecord(
            capability_id="fixture.readonly",
            name="Fixture read-only adapter",
            category="integration",
            purpose="Deterministic test adapter",
            source_url="https://example.invalid/fixture",
            source_publisher="uneXpected test fixture",
            discovered_at=time.time(),
            verified_at=None,
            evidence_refs=("test:fixture-source",),
            reviewer=None,
            adapter_type="mcp",
            provider="fixture",
            required_permissions=("collaborate",),
            dependencies=(),
            cost_notes="No external call",
            risk_notes="Test-only fixture",
            data_access=("fixture-data",),
            version="1.0.0",
            content_sha256=self.source_hash,
            status="discovered",
        )
        self.capabilities.register(self.capability)
        self.capabilities.transition(
            self.capability.capability_id, "reviewed",
            reviewer="test-reviewer", reason="fixture reviewed"
        )
        self.capabilities.transition(
            self.capability.capability_id, "installed", reason="test adapter registered"
        )
        self.capabilities.transition(
            self.capability.capability_id, "enabled", reason="fake adapter verified"
        )
        self.descriptor = ToolDescriptor(
            tool_id="fixture.echo",
            capability_id=self.capability.capability_id,
            name="Fixture echo",
            description="Returns deterministic fixture data",
            source_ref=self.capability.source_url,
            publisher=self.capability.source_publisher,
            adapter_version="1.0.0",
            content_sha256=self.source_hash,
            allowed_agent_ids=("orchestrator",),
            required_permissions=("collaborate",),
            timeout_seconds=2.0,
            max_input_bytes=1024,
            max_output_bytes=1024,
        )
        self.adapter = FakeAdapter(self.descriptor)
        self.boundary = MCPToolBoundary(
            capabilities=self.capabilities,
            agents=self.agents,
            permissions=self.permissions,
            store=self.store,
            max_workers=2,
        )
        self.boundary.register_adapter(self.capability.capability_id, self.adapter)
        self.context = ToolCallContext(
            task_id="parent-task-1",
            agent_id="orchestrator",
            deadline_monotonic=time.monotonic() + 5,
            cancellation_token=CancellationToken(),
        )

    def tearDown(self):
        self.boundary.close()
        self.store.close()
        self.temp.cleanup()

    def test_enabled_verified_adapter_executes_and_audits_only_fingerprints(self):
        result = self.boundary.call(
            "fixture.echo", {"query": "private argument"}, self.context
        )
        self.assertEqual(result.value, {"ok": True})
        self.assertEqual(result.source_ref, self.descriptor.source_ref)
        self.assertEqual(len(self.adapter.calls), 1)
        events = self.store.events(20)
        completed = next(e for e in events if e["event_type"] == "mcp_tool_call_completed")
        payload = json.loads(completed["payload_json"])
        self.assertNotIn("private argument", json.dumps(payload))
        self.assertEqual(payload["tool_id"], "fixture.echo")
        self.assertEqual(len(payload["arguments_sha256"]), 64)

    def test_unknown_tool_is_rejected_before_adapter_call(self):
        with self.assertRaises(MCPToolError):
            self.boundary.call("fixture.missing", {}, self.context)
        self.assertEqual(self.adapter.calls, [])

    def test_role_scope_is_enforced_before_adapter_call(self):
        context = ToolCallContext(
            task_id="other-role-task",
            agent_id="research-scout",
            deadline_monotonic=time.monotonic() + 5,
            cancellation_token=CancellationToken(),
        )
        with self.assertRaises(MCPToolPermissionError):
            self.boundary.call("fixture.echo", {}, context)
        self.assertEqual(self.adapter.calls, [])

    def test_cancelled_or_expired_context_is_rejected_before_adapter_call(self):
        cancelled = CancellationToken()
        cancelled.cancel()
        context = ToolCallContext(
            task_id="cancelled-task",
            agent_id="orchestrator",
            deadline_monotonic=time.monotonic() + 5,
            cancellation_token=cancelled,
        )
        with self.assertRaises(MCPToolTimeout):
            self.boundary.call("fixture.echo", {}, context)
        expired = ToolCallContext(
            task_id="expired-task",
            agent_id="orchestrator",
            deadline_monotonic=time.monotonic() - 1,
            cancellation_token=CancellationToken(),
        )
        with self.assertRaises(MCPToolTimeout):
            self.boundary.call("fixture.echo", {}, expired)
        self.assertEqual(self.adapter.calls, [])

    def test_privileged_scope_requires_action_bound_host_approval(self):
        protected = ToolDescriptor(
            tool_id="fixture.write",
            capability_id=self.capability.capability_id,
            name="Fixture write",
            description="A protected write fixture",
            source_ref=self.capability.source_url,
            publisher=self.capability.source_publisher,
            adapter_version="1.0.0",
            content_sha256=self.source_hash,
            allowed_agent_ids=("orchestrator",),
            required_permissions=("repo_write",),
            timeout_seconds=2.0,
            max_input_bytes=1024,
            max_output_bytes=1024,
        )
        adapter = FakeAdapter(protected)
        self.boundary.register_adapter(self.capability.capability_id, adapter)
        with self.assertRaises(PermissionDenied):
            self.boundary.call("fixture.write", {"path": "README.md"}, self.context)
        self.assertEqual(adapter.calls, [])

    def test_input_and_output_limits_are_enforced(self):
        with self.assertRaises(MCPToolError):
            self.boundary.call("fixture.echo", {"data": "x" * 2000}, self.context)
        oversized = FakeAdapter(self.descriptor, value={"data": "x" * 2000})
        self.boundary.register_adapter(self.capability.capability_id, oversized)
        with self.assertRaises(MCPToolError):
            self.boundary.call("fixture.echo", {}, self.context)
        self.assertEqual(len(oversized.calls), 1)

    def test_unverified_capability_cannot_be_registered(self):
        record = CapabilityRecord(
            capability_id="fixture.unverified",
            name="Unverified adapter",
            category="integration",
            purpose="Must remain unavailable",
            source_url="https://example.invalid/unverified",
            source_publisher="test",
            discovered_at=time.time(),
            verified_at=None,
            evidence_refs=(),
            reviewer=None,
            adapter_type="mcp",
            provider="fixture",
            required_permissions=("collaborate",),
            dependencies=(),
            cost_notes="none",
            risk_notes="unverified",
            data_access=(),
            version="1.0.0",
            content_sha256=self.source_hash,
            status="discovered",
        )
        self.capabilities.register(record)
        descriptor = ToolDescriptor(
            tool_id="fixture.unverified",
            capability_id=record.capability_id,
            name="Unverified",
            description="Must not register",
            source_ref=record.source_url,
            publisher="test",
            adapter_version="1.0.0",
            content_sha256=self.source_hash,
            allowed_agent_ids=("orchestrator",),
            required_permissions=("collaborate",),
            timeout_seconds=1.0,
            max_input_bytes=100,
            max_output_bytes=100,
        )
        with self.assertRaises(MCPToolError):
            self.boundary.register_adapter(
                record.capability_id, FakeAdapter(descriptor)
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
