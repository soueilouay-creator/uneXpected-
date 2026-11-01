from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .evidence import EvidenceEngine


@dataclass
class WorkflowResult:
    status: str
    delivered: bool
    request: dict[str, Any]
    plan: Any = None
    execution: Any = None
    verified_output: Any = None
    delivery: Any = None
    corrections: int = 0
    improvements: int = 0
    verification_history: list[dict[str, Any]] = field(default_factory=list)
    evidence_history: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    learning_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'status': self.status, 'delivered': self.delivered, 'request': self.request,
            'plan': self.plan, 'execution': self.execution, 'verified_output': self.verified_output,
            'delivery': self.delivery, 'corrections': self.corrections,
            'improvements': self.improvements, 'verification_history': list(self.verification_history),
            'evidence_history': list(self.evidence_history), 'error': self.error,
            'learning_error': self.learning_error,
        }


class WorkflowRunner:
    '''Quality-gated lifecycle runner; host-specific stage adapters are injected.'''

    def __init__(self, *, plan: Callable[[dict[str, Any], str | None], Any],
                 execute: Callable[[Any], Any], verify: Callable[[Any, Any], dict[str, Any]],
                 improve: Callable[[Any, str], Any], deliver: Callable[[Any], Any],
                 learn: Callable[[dict[str, Any]], Any], max_corrections: int = 1,
                 max_improvements: int = 3, evidence_required: bool = False) -> None:
        if isinstance(max_corrections, bool) or not isinstance(max_corrections, int) or not 0 <= max_corrections <= 5:
            raise ValueError('max_corrections must be an integer between 0 and 5.')
        if isinstance(max_improvements, bool) or not isinstance(max_improvements, int) or not 1 <= max_improvements <= 5:
            raise ValueError('max_improvements must be an integer between 1 and 5.')
        self.plan_stage, self.execute_stage, self.verify_stage = plan, execute, verify
        self.improve_stage, self.deliver_stage, self.learn_stage = improve, deliver, learn
        self.max_corrections = max_corrections
        if type(evidence_required) is not bool:
            raise ValueError('evidence_required must be a boolean.')
        self.max_improvements = max_improvements
        self.evidence_required = evidence_required

    def _apply_evidence_gate(self, verification: Any, candidate: Any,
                             result: WorkflowResult) -> Any:
        if not isinstance(verification, dict):
            return verification
        report = verification.get('evidence_report')
        if isinstance(report, dict):
            result.evidence_history.append(dict(report))
        if not self.evidence_required:
            return verification
        evidence_candidate = candidate.get('text') if isinstance(candidate, dict) and 'text' in candidate else candidate
        if EvidenceEngine.is_current(report, evidence_candidate):
            return verification
        gated = dict(verification)
        summary = report.get('summary') if isinstance(report, dict) else None
        reason = summary or 'A current, passing evidence report is required.'
        reviewer_feedback = str(gated.get('feedback') or '')
        gated['passed'] = False
        gated['feedback'] = 'Evidence gate blocked delivery: ' + str(reason)
        if reviewer_feedback:
            gated['feedback'] += '\nReviewer feedback: ' + reviewer_feedback
        return gated

    def run(self, request: dict[str, Any]) -> WorkflowResult:
        if not isinstance(request, dict):
            raise TypeError('request must be a dictionary.')
        result = WorkflowResult(status='running', delivered=False, request=dict(request))
        feedback = None
        try:
            while True:
                result.plan = self.plan_stage(result.request, feedback)
                result.execution = self.execute_stage(result.plan)
                verification = self.verify_stage(result.execution, result.plan)
                verification = self._apply_evidence_gate(verification, result.execution, result)
                if not isinstance(verification, dict) or type(verification.get('passed')) is not bool:
                    raise ValueError('verify must return a dictionary with a boolean passed field.')
                feedback = str(verification.get('feedback') or '')
                result.verification_history.append({
                    'phase': 'before_improvement', 'passed': verification['passed'], 'feedback': feedback,
                    'attempt': len(result.verification_history) + 1,
                    'task_id': verification.get('task_id'), 'verification_type': verification.get('verification_type'),
                    'reviewer_agent': verification.get('reviewer_agent'),
                    'evidence_passed': (verification.get('evidence_report') or {}).get('passed')
                        if isinstance(verification.get('evidence_report'), dict) else None,
                    'evidence_summary': (verification.get('evidence_report') or {}).get('summary')
                        if isinstance(verification.get('evidence_report'), dict) else None,
                    'candidate_sha256': (verification.get('evidence_report') or {}).get('candidate_sha256')
                        if isinstance(verification.get('evidence_report'), dict) else None,
                })
                if not verification['passed']:
                    if result.corrections >= self.max_corrections:
                        result.status = 'blocked_verification'
                        result.error = feedback or 'Verification failed; correction budget exhausted.'
                        break
                    result.corrections += 1
                    continue

                candidate_output = result.execution
                for improvement_iteration in range(1, self.max_improvements + 1):
                    candidate_output = self.improve_stage(candidate_output, feedback)
                    result.improvements += 1
                    final_verification = self.verify_stage(candidate_output, result.plan)
                    final_verification = self._apply_evidence_gate(final_verification, candidate_output, result)
                    if not isinstance(final_verification, dict) or type(final_verification.get('passed')) is not bool:
                        raise ValueError('verify must return a dictionary with a boolean passed field.')
                    final_feedback = str(final_verification.get('feedback') or '')
                    phase = 'after_improvement' if improvement_iteration == 1 else f'after_improvement_{improvement_iteration}'
                    result.verification_history.append({
                        'phase': phase, 'passed': final_verification['passed'], 'feedback': final_feedback,
                        'attempt': len(result.verification_history) + 1,
                        'improvement_iteration': improvement_iteration,
                        'task_id': final_verification.get('task_id'),
                        'verification_type': final_verification.get('verification_type'),
                        'reviewer_agent': final_verification.get('reviewer_agent'),
                        'evidence_passed': (final_verification.get('evidence_report') or {}).get('passed')
                            if isinstance(final_verification.get('evidence_report'), dict) else None,
                        'evidence_summary': (final_verification.get('evidence_report') or {}).get('summary')
                            if isinstance(final_verification.get('evidence_report'), dict) else None,
                        'candidate_sha256': (final_verification.get('evidence_report') or {}).get('candidate_sha256')
                            if isinstance(final_verification.get('evidence_report'), dict) else None,
                    })
                    if final_verification['passed']:
                        result.verified_output = candidate_output
                        result.delivery = self.deliver_stage(result.verified_output)
                        result.status, result.delivered = 'delivered', True
                        break
                    feedback = 'Post-improvement verification failed: ' + (
                        final_feedback or 'No reviewer feedback supplied.'
                    )

                if result.delivered:
                    break
                if result.corrections >= self.max_corrections:
                    result.status = 'blocked_verification'
                    result.error = (
                        f'Improvement budget exhausted after {self.max_improvements} round(s). '
                        + (feedback or 'The final candidate did not pass independent verification.')
                    )
                    break
                result.corrections += 1
        except Exception as exc:
            result.status = 'blocked_execution'
            result.error = f'{type(exc).__name__}: workflow stage failed'
        finally:
            record = {
                'request': result.request, 'status': result.status, 'delivered': result.delivered,
                'corrections': result.corrections, 'improvements': result.improvements,
                'verification_history': list(result.verification_history),
                'evidence_history': list(result.evidence_history), 'error': result.error,
            }
            try:
                self.learn_stage(record)
            except Exception as exc:
                result.learning_error = f'{type(exc).__name__}: learning stage failed'
        return result
