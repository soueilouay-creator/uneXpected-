from __future__ import annotations
from dataclasses import dataclass, field
from threading import Event
from typing import Any
import time, uuid

class RuntimeErrorBase(Exception): pass
class UnknownAgent(RuntimeErrorBase): pass
class PermissionDenied(RuntimeErrorBase): pass
class CycleLimitError(RuntimeErrorBase): pass
class BudgetExceeded(RuntimeErrorBase): pass
class DeadlineExceeded(RuntimeErrorBase): pass
class Cancelled(RuntimeErrorBase): pass
class ImprovementRejected(RuntimeErrorBase): pass

@dataclass(frozen=True)
class TaskRequest:
    task_id: str
    agent_id: str
    objective: str
    inputs: dict[str, Any] = field(default_factory=dict)
    required_permissions: tuple[str, ...] = ()
    deadline_seconds: float = 30.0
    max_steps: int = 6
    idempotency_key: str | None = None
    source_refs: tuple[str, ...] = ()
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(cls, agent_id: str, objective: str, **kwargs: Any) -> 'TaskRequest':
        return cls(task_id=kwargs.pop('task_id', str(uuid.uuid4())), agent_id=agent_id, objective=objective, **kwargs)

@dataclass(frozen=True)
class AgentMessage:
    protocol_version: str
    message_id: str
    task_id: str
    sender_agent_id: str
    recipient_agent_id: str
    objective: str
    payload: dict[str, Any]
    provenance: tuple[str, ...] = ()
    requested_permissions: tuple[str, ...] = ('collaborate',)
    depth: int = 1

@dataclass
class TaskResult:
    task_id: str
    agent_id: str
    status: str
    output: str = ''
    provenance: tuple[str, ...] = ()
    attempts: int = 0
    error: str | None = None
    idempotent_replay: bool = False
    started_at: float | None = None
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {'task_id':self.task_id,'agent_id':self.agent_id,'status':self.status,'output':self.output,
                'provenance':list(self.provenance),'attempts':self.attempts,'error':self.error,
                'idempotent_replay':self.idempotent_replay,'started_at':self.started_at,'finished_at':self.finished_at}
    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> 'TaskResult':
        return cls(task_id=d['task_id'],agent_id=d['agent_id'],status=d['status'],output=d.get('output',''),
                   provenance=tuple(d.get('provenance',[])),attempts=d.get('attempts',0),error=d.get('error'),
                   idempotent_replay=d.get('idempotent_replay',False),started_at=d.get('started_at'),finished_at=d.get('finished_at'))

@dataclass(frozen=True)
class ApprovalContext:
    approval_id: str
    approver: str
    approved_permissions: frozenset[str]
    rationale: str
    created_at: float = field(default_factory=time.time)
    action_digest: str = ''

class CancellationToken:
    def __init__(self) -> None: self._event = Event()
    def cancel(self) -> None: self._event.set()
    @property
    def cancelled(self) -> bool: return self._event.is_set()

@dataclass(frozen=True)
class EvaluationReport:
    benchmark_id: str
    scenario_ids: tuple[str, ...]
    score: float
    critical_checks: dict[str, bool]
    noncritical_passed: int
    noncritical_total: int
    notes: str = ''
    @property
    def noncritical_rate(self) -> float:
        return self.noncritical_passed / self.noncritical_total if self.noncritical_total else 0.0
    @property
    def critical_pass(self) -> bool:
        return bool(self.critical_checks) and all(self.critical_checks.values())
    def to_dict(self) -> dict[str, Any]:
        return {'benchmark_id':self.benchmark_id,'scenario_ids':list(self.scenario_ids),'score':self.score,
                'critical_checks':self.critical_checks,'noncritical_passed':self.noncritical_passed,
                'noncritical_total':self.noncritical_total,'notes':self.notes}
    @classmethod
    def from_dict(cls,d:dict[str,Any])->'EvaluationReport':
        return cls(d['benchmark_id'],tuple(d['scenario_ids']),float(d['score']),dict(d['critical_checks']),
                   int(d['noncritical_passed']),int(d['noncritical_total']),d.get('notes',''))
