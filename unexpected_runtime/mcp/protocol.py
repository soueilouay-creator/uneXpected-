from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence
import math
import re


class CancellationLike(Protocol):
    @property
    def cancelled(self) -> bool: ...

    def cancel(self) -> None: ...


@dataclass(frozen=True)
class ToolDescriptor:
    """Reviewed metadata for one tool exposed by a host-registered adapter.

    Descriptor metadata is not an authorization grant. Runtime permission
    checks are performed for every call by the boundary.
    """

    tool_id: str
    capability_id: str
    name: str
    description: str
    source_ref: str
    publisher: str
    adapter_version: str
    content_sha256: str
    allowed_agent_ids: tuple[str, ...]
    required_permissions: tuple[str, ...] = ()
    timeout_seconds: float = 10.0
    max_input_bytes: int = 64 * 1024
    max_output_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        required = (
            self.tool_id, self.capability_id, self.name, self.description,
            self.source_ref, self.publisher, self.adapter_version,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ValueError("Tool descriptor identity, source and description fields must be non-empty strings.")
        if not re.fullmatch(r"[0-9a-f]{64}", self.content_sha256):
            raise ValueError("Tool descriptor content_sha256 must be a lowercase SHA-256 digest.")
        if not self.allowed_agent_ids or any(not isinstance(item, str) or not item.strip() for item in self.allowed_agent_ids):
            raise ValueError("Tool descriptor must declare at least one allowed role ID.")
        if len(set(self.allowed_agent_ids)) != len(self.allowed_agent_ids):
            raise ValueError("Tool descriptor role IDs must be unique.")
        if any(not isinstance(item, str) or not item.strip() for item in self.required_permissions):
            raise ValueError("Tool descriptor permission scopes must be non-empty strings.")
        if len(set(self.required_permissions)) != len(self.required_permissions):
            raise ValueError("Tool descriptor permission scopes must be unique.")
        if isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float)):
            raise ValueError("Tool timeout must be a finite number.")
        if not math.isfinite(float(self.timeout_seconds)) or not 0.05 <= float(self.timeout_seconds) <= 60.0:
            raise ValueError("Tool timeout must be between 0.05 and 60 seconds.")
        for label, value in (("max_input_bytes", self.max_input_bytes), ("max_output_bytes", self.max_output_bytes)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1024 * 1024:
                raise ValueError(f"{label} must be an integer between 1 and 1048576.")


@dataclass(frozen=True)
class ToolCallContext:
    task_id: str
    agent_id: str
    deadline_monotonic: float
    cancellation_token: CancellationLike


@dataclass(frozen=True)
class ToolResult:
    """Untrusted adapter output with source and adapter provenance."""

    value: Any
    tool_id: str
    capability_id: str
    source_ref: str
    adapter_version: str
    adapter_sha256: str
    trust_status: str = "untrusted"


class MCPAdapter(Protocol):
    """Host-provided adapter boundary; implementations may wrap MCP clients."""

    def describe(self) -> Sequence[ToolDescriptor]: ...

    def call(self, tool_id: str, arguments: dict[str, Any], context: ToolCallContext) -> Any: ...
