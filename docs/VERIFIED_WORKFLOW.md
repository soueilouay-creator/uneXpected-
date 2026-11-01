# Verified workflow lifecycle

## Canonical sequence

**Request → Plan → Execute → Verify → Improve → Verify ↻ → Deliver → Learn**

The runtime applies a quality gate before delivery. Initial execution corrections and post-review improvement iterations use separate bounded budgets. After the initial candidate passes review, the same candidate is improved and independently reviewed repeatedly until the latest version passes or the configured improvement budget is exhausted.

## Native runtime path

`Coordinator.run_lifecycle(agent_id, objective, inputs, max_corrections=1, max_improvement_iterations=2, deadline_seconds=60)` is the default specialist-backed path.

1. **Request:** stores the target role, objective and supplied inputs for this cycle.
2. **Plan:** calls the registered `project-manager` role for ordered steps, dependencies, risks and acceptance criteria.
3. **Execute:** calls the selected registered specialist role with the request and plan.
4. **Verify:** calls the independent `code-reviewer` role. Its first non-empty line must be exactly `VERDICT: PASS` or `VERDICT: FAIL`. Missing, malformed or failed verdicts fail closed.
5. **Improve ↔ Verify:** after the initial PASS, calls the selected specialist to improve the current candidate using the latest reviewer feedback, then calls `code-reviewer` again on that exact improved candidate. A failed post-improvement review feeds the next improvement pass; the task is not restarted or replanned. Every improved candidate is reviewed before another pass.
6. **Deliver:** returns the latest candidate only after its review passes. If every allowed improvement iteration fails, status is `blocked_verification` and neither `verified_output` nor `delivery` is populated.
7. **Learn:** records the terminal result, correction count, improvement-iteration count, verification history and task provenance through `ImprovementGovernor.record_outcome`, including blocked cycles.

Each stage uses the regular coordinator invocation path and therefore inherits the configured provider, role instructions, timeouts, audit records and permission policy. This is an independent role-based model review—not a deterministic test suite, formal proof, or automatic verification of external facts. Tasks needing executable tests, source checks or domain-specific measurements must supply and run those checks as part of the specialist's work. The lifecycle itself does not grant privileged permissions or configure external tools.

## Retry and result contract

- Native coordinator correction budget is 0–2. The generic `WorkflowRunner` primitive supports 0–5 for host-specific use.
- `max_improvement_iterations` defaults to 2 and accepts integers from 1 to 4. The generic runner, coordinator, CLI and HTTP interface use the same default and range.
- Initial verification FAIL returns to planning and execution while the correction budget remains.
- Once initial verification passes, each Improve → Verify cycle operates on the same current candidate. Review feedback from a failed iteration is supplied to the next improvement call.
- The iteration counter records actual improvement calls. Verification history records `iteration=0` for the initial review and `iteration=1..N` for each improved candidate.
- Exhausting the improvement budget produces `blocked_verification`; stage exceptions produce `blocked_execution`.
- No improve call occurs after a failed initial review. No delivery call occurs unless the initial review and the review of the latest improved candidate pass.
- Learning is attempted for delivered and blocked cycles. If learning fails, `learning_error` is surfaced separately; it does not turn a blocked cycle into success.
- `deadline_seconds` is a per-stage coordinator invocation deadline, not a total wall-clock budget for the entire cycle.

## Interfaces

- Python: `Coordinator.run_lifecycle(..., max_improvement_iterations=2)` for native role orchestration; `Coordinator.run_workflow(..., max_improvement_iterations=2)` for explicitly injected host adapters.
- CLI: `python -m unexpected_runtime.cli lifecycle <agent_id> --objective '...' --inputs '{}' --max-improvement-iterations 2`.
- Authenticated HTTP: `POST /v1/lifecycle` with `agent_id`, `objective`, optional `inputs`, `deadline_seconds`, `max_corrections` and `max_improvement_iterations`.

The lifecycle HTTP endpoint returns 200 only for `status=delivered`; blocked cycles return 502. It accepts 0–2 corrections and 1–4 improvement iterations. The normal `POST /v1/invoke` endpoint remains available and unchanged.

## Delivery and self-improvement boundaries

`deliver` currently packages a local result for the caller. It does not publish content, send mail, write repositories, deploy, pay, delete or alter accounts. Those actions continue to require their own separately authorized integration and approval.

`Learn` stores outcomes; it does not rewrite role instructions or automatically promote code. The existing self-improvement governor's fixed benchmarks, regression checks, evidence fingerprints, human approval for protected changes and rollback rules remain authoritative.

The 38-role registry and existing provider/permission boundaries are preserved. Runtime activation in a hosted service still requires a separately verified deployment and live provider smoke test; a passing mock CI run does not prove live model access or deployment.
