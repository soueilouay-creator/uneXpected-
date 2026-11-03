from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Any
import hashlib
import json
import math
import time

from ..approvals import canonical_action_digest
from ..models import PermissionDenied
from .protocol import MCPAdapter, ToolCallContext, ToolDescriptor, ToolResult


class MCPToolError(RuntimeError):
    """A tool is unknown, unavailable, untrusted or returned an invalid result."""


class MCPToolPermissionError(PermissionDenied):
    """The role or approval policy rejected a tool invocation."""


class MCPToolTimeout(MCPToolError):
    """A tool deadline expired or its task was cancelled."""


@dataclass(frozen=True)
class _RegisteredTool:
    capability_id: str
    adapter: MCPAdapter
    descriptor: ToolDescriptor


class MCPToolBoundary:
    """Governed call boundary for host-registered MCP-compatible adapters.

    This class deliberately does not discover servers or open network
    connections. A host must supply an adapter after capability review and
    verification. Every invocation rechecks capability state and role scopes.
    """

    def __init__(self, *, capabilities, agents, permissions, store, max_workers: int = 4):
        if isinstance(max_workers, bool) or not isinstance(max_workers, int) or not 1 <= max_workers <= 8:
            raise ValueError("max_workers must be an integer between 1 and 8.")
        self.capabilities = capabilities
        self.agents = agents
        self.permissions = permissions
        self.store = store
        self._tools: dict[str, _RegisteredTool] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="unexpected-mcp")
        self._closed = False

    def register_adapter(self, capability_id: str, adapter: MCPAdapter) -> tuple[str, ...]:
        if self._closed:
            raise MCPToolError("MCP tool boundary is closed.")
        try:
            capability = self.capabilities.get(capability_id)
        except Exception as exc:
            raise MCPToolError(f"Capability is unavailable ({type(exc).__name__}).") from None
        if capability.status != "enabled" or capability.adapter_type != "mcp":
            raise MCPToolError("MCP adapter requires an enabled, verified MCP capability.")
        if not callable(getattr(adapter, "describe", None)) or not callable(getattr(adapter, "call", None)):
            raise MCPToolError("Adapter must implement describe() and call().")
        try:
            descriptors = adapter.describe()
        except Exception as exc:
            raise MCPToolError(f"Adapter descriptor lookup failed ({type(exc).__name__}).") from None
        if not isinstance(descriptors, (list, tuple)) or not descriptors:
            raise MCPToolError("Adapter must return a non-empty list of tool descriptors.")

        validated: list[ToolDescriptor] = []
        seen: set[str] = set()
        for descriptor in descriptors:
            if not isinstance(descriptor, ToolDescriptor):
                raise MCPToolError("Adapter returned an invalid tool descriptor.")
            if descriptor.capability_id != capability_id:
                raise MCPToolError("Tool descriptor capability ID does not match the registered adapter.")
            if descriptor.content_sha256 != capability.content_sha256:
                raise MCPToolError("Tool descriptor digest does not match the verified capability.")
            if descriptor.source_ref != capability.source_url or descriptor.publisher != capability.source_publisher:
                raise MCPToolError("Tool descriptor provenance does not match the verified capability.")
            if descriptor.adapter_version != capability.version:
                raise MCPToolError("Tool descriptor version does not match the verified capability.")
            if descriptor.tool_id in seen:
                raise MCPToolError("Adapter returned duplicate tool IDs.")
            current = self._tools.get(descriptor.tool_id)
            if current and current.capability_id != capability_id:
                raise MCPToolError("Tool ID is already registered by another capability.")
            seen.add(descriptor.tool_id)
            validated.append(descriptor)

        for descriptor in validated:
            self._tools[descriptor.tool_id] = _RegisteredTool(capability_id, adapter, descriptor)
        self.store.log_event(
            "mcp_adapter_registered",
            payload={
                "capability_id": capability_id,
                "tool_ids": [item.tool_id for item in validated],
                "content_sha256": capability.content_sha256,
                "source_ref": capability.source_url,
            },
        )
        return tuple(item.tool_id for item in validated)

    @staticmethod
    def _json_bytes(value: Any) -> bytes:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")

    def _audit(self, event_type: str, context: ToolCallContext, descriptor: ToolDescriptor,
               **metadata: Any) -> None:
        safe = {
            "tool_id": descriptor.tool_id,
            "capability_id": descriptor.capability_id,
            "source_ref": descriptor.source_ref,
            "adapter_sha256": descriptor.content_sha256,
            **metadata,
        }
        self.store.log_event(event_type, context.task_id, context.agent_id, safe)

    def call(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        context: ToolCallContext,
        *,
        approval=None,
    ) -> ToolResult:
        if self._closed:
            raise MCPToolError("MCP tool boundary is closed.")
        registered = self._tools.get(tool_id)
        if registered is None:
            raise MCPToolError("Unknown MCP tool ID.")
        descriptor = registered.descriptor

        try:
            capability = self.capabilities.get(registered.capability_id)
            role = self.agents.get(context.agent_id)
        except Exception as exc:
            raise MCPToolError(f"Tool identity lookup failed ({type(exc).__name__}).") from None
        if capability.status != "enabled" or capability.adapter_type != "mcp":
            raise MCPToolError("Tool capability is no longer enabled.")
        if capability.content_sha256 != descriptor.content_sha256:
            raise MCPToolError("Tool capability digest changed after registration.")
        if context.agent_id not in descriptor.allowed_agent_ids:
            self._audit("mcp_tool_call_rejected", context, descriptor, reason="role_scope")
            raise MCPToolPermissionError(f"Role {context.agent_id} is not permitted to call this tool.")
        if not isinstance(context.task_id, str) or not context.task_id.strip():
            raise MCPToolError("Tool call requires a task ID.")
        if not isinstance(arguments, dict):
            raise MCPToolError("Tool arguments must be a JSON object.")

        try:
            argument_bytes = self._json_bytes(arguments)
        except (TypeError, ValueError, OverflowError):
            self._audit("mcp_tool_call_rejected", context, descriptor, reason="invalid_arguments")
            raise MCPToolError("Tool arguments must be finite, serializable JSON.") from None
        if len(argument_bytes) > descriptor.max_input_bytes:
            self._audit(
                "mcp_tool_call_rejected", context, descriptor,
                reason="input_too_large", input_bytes=len(argument_bytes),
            )
            raise MCPToolError("Tool argument payload exceeds the configured byte limit.")

        if context.cancellation_token.cancelled:
            self._audit("mcp_tool_call_rejected", context, descriptor, reason="cancelled")
            raise MCPToolTimeout("Tool task was cancelled before adapter dispatch.")
        remaining = float(context.deadline_monotonic) - time.monotonic()
        timeout_seconds = min(float(descriptor.timeout_seconds), remaining)
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            self._audit("mcp_tool_call_rejected", context, descriptor, reason="deadline_expired")
            raise MCPToolTimeout("Tool task deadline expired before adapter dispatch.")

        argument_digest = hashlib.sha256(argument_bytes).hexdigest()
        action_details = {
            "action": "mcp.tool_call",
            "task_id": context.task_id,
            "agent_id": context.agent_id,
            "capability_id": registered.capability_id,
            "tool_id": descriptor.tool_id,
            "arguments_sha256": argument_digest,
            "adapter_sha256": descriptor.content_sha256,
        }
        try:
            for scope in descriptor.required_permissions:
                self.permissions.authorize(
                    role, scope, approval,
                    action_details=action_details,
                )
        except PermissionDenied:
            self._audit(
                "mcp_tool_call_rejected", context, descriptor,
                reason="permission_denied", arguments_sha256=argument_digest,
            )
            raise
        except Exception as exc:
            self._audit(
                "mcp_tool_call_rejected", context, descriptor,
                reason="permission_check_failed", error_type=type(exc).__name__,
            )
            raise MCPToolPermissionError("Tool permission check failed closed.") from None

        self._audit(
            "mcp_tool_call_started", context, descriptor,
            arguments_sha256=argument_digest, input_bytes=len(argument_bytes),
            timeout_seconds=timeout_seconds,
        )
        future = self._executor.submit(
            registered.adapter.call, descriptor.tool_id, arguments, context
        )
        try:
            value = future.result(timeout=timeout_seconds)
        except FutureTimeout:
            future.cancel()
            cancel = getattr(context.cancellation_token, "cancel", None)
            if callable(cancel):
                cancel()
            self._audit(
                "mcp_tool_call_failed", context, descriptor,
                reason="timeout", arguments_sha256=argument_digest,
            )
            raise MCPToolTimeout("MCP adapter exceeded its bounded deadline.") from None
        except Exception as exc:
            self._audit(
                "mcp_tool_call_failed", context, descriptor,
                reason="adapter_error", error_type=type(exc).__name__,
                arguments_sha256=argument_digest,
            )
            raise MCPToolError(f"MCP adapter call failed ({type(exc).__name__}).") from None

        if context.cancellation_token.cancelled:
            self._audit(
                "mcp_tool_call_failed", context, descriptor,
                reason="cancelled_after_dispatch", arguments_sha256=argument_digest,
            )
            raise MCPToolTimeout("Tool result discarded because its task was cancelled.")
        try:
            output_bytes = self._json_bytes(value)
        except (TypeError, ValueError, OverflowError):
            self._audit(
                "mcp_tool_call_failed", context, descriptor,
                reason="invalid_result", arguments_sha256=argument_digest,
            )
            raise MCPToolError("MCP adapter returned a non-JSON or non-finite result.") from None
        if len(output_bytes) > descriptor.max_output_bytes:
            self._audit(
                "mcp_tool_call_failed", context, descriptor,
                reason="output_too_large", output_bytes=len(output_bytes),
                arguments_sha256=argument_digest,
            )
            raise MCPToolError("MCP adapter result exceeds the configured byte limit.")

        result_digest = hashlib.sha256(output_bytes).hexdigest()
        self._audit(
            "mcp_tool_call_completed", context, descriptor,
            arguments_sha256=argument_digest, input_bytes=len(argument_bytes),
            result_sha256=result_digest, result_bytes=len(output_bytes),
        )
        return ToolResult(
            value=value,
            tool_id=descriptor.tool_id,
            capability_id=registered.capability_id,
            source_ref=descriptor.source_ref,
            adapter_version=descriptor.adapter_version,
            adapter_sha256=descriptor.content_sha256,
        )

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._executor.shutdown(wait=False, cancel_futures=True)
