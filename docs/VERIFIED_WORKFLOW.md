# Verified workflow lifecycle

## Canonical sequence

**Request → Plan → Execute → Verify → Improve & Deliver → Learn ↻**

This lifecycle is the quality gate for work orchestrated by an uneXpected host:

1. **Request** captures the user's objective, constraints and source context.
2. **Plan** produces a bounded plan. A failed verification is fed back into planning.
3. **Execute** performs the planned work through explicitly injected, authorized host adapters.
4. **Verify** returns an explicit boolean pass/fail result and feedback. A missing or malformed verdict blocks delivery.
5. **Improve & Deliver** runs only after verification passes. Improvement transforms the execution output; delivery receives only that improved output.
6. **Learn** records the outcome after success or blockage so the next cycle can use the evidence.

## Runtime contract

The `unexpected_runtime.workflow.WorkflowRunner` module implements the quality-gated lifecycle. Host integrations provide the six stage callbacks; the runner does not pretend that a provider, connector, file store, publisher or background worker is configured.

- `plan(request, feedback)` returns a plan. The first call receives `feedback=None`; subsequent calls receive the last failed verification feedback.
- `execute(plan)` returns the execution output.
- `verify(execution, plan)` must return `{"passed": bool, "feedback": str}`.
- `improve(execution, feedback)` returns the improved deliverable candidate.
- `deliver(improved_output)` is called only after a passing verification.
- `learn(record)` receives the terminal status and verification history, including blocked outcomes.
- `max_corrections` is bounded from 0 through 5. Exhaustion returns `blocked_verification` and never calls improve or deliver.
- Stage exceptions return `blocked_execution`; learning is still attempted. Learning failures are surfaced separately as `learning_error` and do not convert a blocked task into success.

## Integration and security boundaries

The runner is a deterministic orchestration primitive, not an automatic deployment or a claim that all 38 roles have been migrated. A host must explicitly bind callbacks to the existing coordinator, specialist roles, verification tools, improvement governor and delivery destinations. Each adapter must enforce the existing permission and approval model. Publishing, repository writes, deployments, payments, deletion, account changes and protected policy changes remain denied unless the host's existing authorization gates approve them.

The existing registry, role profiles, skill manifests, provider selection, and protected self-improvement promotion rules are unchanged by this lifecycle module. Runtime activation requires a host integration, regression tests, and a separately verified deployment.
