from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


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
    verification_history: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    learning_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            'status': self.status, 'delivered': self.delivered, 'request': self.request,
            'plan': self.plan, 'execution': self.execution, 'verified_output': self.verified_output,
            'delivery': self.delivery, 'corrections': self.corrections,
            'verification_history': list(self.verification_history), 'error': self.error,
            'learning_error': self.learning_error,
        }


class WorkflowRunner:
    '''Quality-gated lifecycle runner; host-specific stage adapters are injected.'''

    def __init__(self, *, plan: Callable[[dict[str, Any], str | None], Any],
                 execute: Callable[[Any], Any], verify: Callable[[Any, Any], dict[str, Any]],
                 improve: Callable[[Any, str], Any], deliver: Callable[[Any], Any],
                 learn: Callable[[dict[str, Any]], Any], max_corrections: int = 1) -> None:
        if isinstance(max_corrections, bool) or not isinstance(max_corrections, int) or not 0 <= max_corrections <= 5:
            raise ValueError('max_corrections must be an integer between 0 and 5.')
        self.plan_stage, self.execute_stage, self.verify_stage = plan, execute, verify
        self.improve_stage, self.deliver_stage, self.learn_stage = improve, deliver, learn
        self.max_corrections = max_corrections

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
                if not isinstance(verification, dict) or type(verification.get('passed')) is not bool:
                    raise ValueError('verify must return a dictionary with a boolean passed field.')
                feedback = str(verification.get('feedback') or '')
                result.verification_history.append({'phase': 'before_improvement', 'passed': verification['passed'], 'feedback': feedback,
                                                    'attempt': len(result.verification_history) + 1,
                                                    'task_id': verification.get('task_id'), 'verification_type': verification.get('verification_type'),
                                                    'reviewer_agent': verification.get('reviewer_agent')})
                if verification['passed']:
                    result.verified_output = self.improve_stage(result.execution, feedback)
                    final_verification = self.verify_stage(result.verified_output, result.plan)
                    if not isinstance(final_verification, dict) or type(final_verification.get('passed')) is not bool:
                        raise ValueError('verify must return a dictionary with a boolean passed field.')
                    final_feedback = str(final_verification.get('feedback') or '')
                    result.verification_history.append({'phase': 'after_improvement',
                                                        'passed': final_verification['passed'],
                                                        'feedback': final_feedback,
                                                        'attempt': len(result.verification_history) + 1,
                                                        'task_id': final_verification.get('task_id'),
                                                        'verification_type': final_verification.get('verification_type'),
                                                        'reviewer_agent': final_verification.get('reviewer_agent')})
                    if final_verification['passed']:
                        result.delivery = self.deliver_stage(result.verified_output)
                        result.status, result.delivered = 'delivered', True
                        break
                    feedback = 'Post-improvement verification failed: ' + (final_feedback or 'No reviewer feedback supplied.')
                    if result.corrections >= self.max_corrections:
                        result.status = 'blocked_verification'
                        result.error = feedback
                        break
                    result.corrections += 1
                    continue
                if result.corrections >= self.max_corrections:
                    result.status = 'blocked_verification'
                    result.error = feedback or 'Verification failed; correction budget exhausted.'
                    break
                result.corrections += 1
        except Exception as exc:
            result.status = 'blocked_execution'
            result.error = f'{type(exc).__name__}: workflow stage failed'
        finally:
            record = {'request': result.request, 'status': result.status, 'delivered': result.delivered,
                      'corrections': result.corrections, 'verification_history': list(result.verification_history),
                      'error': result.error}
            try:
                self.learn_stage(record)
            except Exception as exc:
                result.learning_error = f'{type(exc).__name__}: learning stage failed'
        return result
