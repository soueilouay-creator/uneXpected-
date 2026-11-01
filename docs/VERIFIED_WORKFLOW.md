# Verified workflow lifecycle

## Canonical sequence

**Request → Plan → Execute → Evidence Verify → Independent Review → Improve → Re-run Evidence + Review ↻ → Deliver → Learn**

The native lifecycle is now evidence-driven. A model reviewer is still required, but a PASS is only one part of the gate. Required deterministic evidence must also pass for the exact candidate being delivered.

## Native runtime path

`Coordinator.run_lifecycle(agent_id, objective, inputs, max_corrections=1, max_improvements=3, deadline_seconds=60)` is the default specialist-backed path.

1. **Request:** stores the target role, objective and supplied inputs for this cycle.
2. **Plan:** calls `project-manager` for a strict JSON plan containing ordered steps and a structured acceptance contract. The contract uses unique criterion IDs, an evidence kind, description, measurable target and required flag. Callers may supply `inputs.acceptance_criteria` to override the planner's proposed contract; it is validated by the same schema.
3. **Execute:** calls the selected registered specialist role with the request, plan and acceptance contract.
4. **Evidence Verify:** `EvidenceEngine` invokes registered host checkers for each criterion. The built-in artifact checker verifies only that candidate content is non-empty. Test, source and measurement checkers must be explicitly registered by the host. A missing checker is `unverified`, never PASS.
5. **Independent Review:** `code-reviewer` receives the request, plan, acceptance criteria, candidate and evidence report. It must return exactly `VERDICT: PASS` or `VERDICT: FAIL` on its first line and justify its assessment with criterion IDs and evidence references. The deterministic gate independently checks that the evidence report is passing and bound to the candidate's SHA-256 fingerprint. A reviewer PASS cannot override missing, failed, malformed or stale evidence.
6. **Iterative Improve & Verify:** after the initial evidence and review both pass, the specialist improves the same candidate. Every revised candidate is checked again by the configured evidence checkers and the independent reviewer. Failed feedback feeds the next bounded improvement round. Only a candidate with fresh passing evidence and a passing review can be delivered.
7. **Learn:** records the terminal result, verification history, evidence history, candidate fingerprints, correction count, improvement count and task provenance through `ImprovementGovernor.record_outcome`, including blocked cycles.

## Evidence checker contract

Register trusted callables when constructing `Coordinator(evidence_checkers=...)`. The mapping keys are `test`, `source` and `measurement`; the built-in `artifact` checker cannot be replaced. Each checker receives `(candidate, criterion, context)` and returns a dictionary with boolean `passed`, measured `actual` and a non-empty `evidence_ref`. `expected` defaults to the criterion target. Checker exceptions, malformed outputs, missing provenance and missing checker configuration fail closed.

The runtime never executes arbitrary commands supplied by the model. The optional test adapter supports a fixed `evidence-engine` profile only. The Docker backend uses an immutable image with network disabled, read-only root, dropped capabilities, non-root identity and resource limits. The Render backend uses an ephemeral Render Sandboxes microVM with outbound network denied and explicit termination. Both stage only four allowlisted source files; no credentials or general workspace are uploaded. Cleanup failure prevents a passing test result.

The optional source adapter retrieves text in the trusted host using exact HTTPS domain allowlists, DNS public-IP validation and connection pinning, no redirects, bounded response size/time and raw-content SHA-256 provenance. The retrieved title/excerpt is included for the independent reviewer. Retrieval success alone is not semantic source validation: the reviewer must decide whether the document supports the candidate. Measurement adapters still require a separate host implementation. Until a given adapter is configured, required criteria of that kind remain unverified and block delivery. The default artifact check is only a non-empty-output check, not a claim that the answer is factually correct.

See [EVIDENCE_GATE.md](EVIDENCE_GATE.md) for the full contract and integration example.

## Retry and result contract

- Native coordinator correction budget is 0–2. The generic `WorkflowRunner` primitive supports 0–5 for host-specific use.
- A failed initial evidence or review gate returns to planning with reviewer and evidence feedback while correction budget remains.
- A failed post-improvement gate returns the candidate and feedback to the specialist for another improvement round. If the improvement budget is exhausted, the runner uses the remaining bounded correction/replanning budget or blocks.
- Exhausting the budgets produces `blocked_verification`; stage exceptions produce `blocked_execution`.
- No improve call occurs after a failed initial gate. No delivery call occurs unless the initial evidence and review pass and an improved candidate subsequently passes both again.
- Learning is attempted for delivered and blocked cycles. If learning fails, `learning_error` is surfaced separately; it does not turn a blocked cycle into success.
- `deadline_seconds` is a per-stage coordinator invocation deadline, not a total wall-clock budget for the entire cycle.

## Interfaces

- Python: `Coordinator.run_lifecycle(...)` for native role orchestration; `Coordinator.run_workflow(...)` for explicitly injected host adapters.
- CLI: `python -m unexpected_runtime.cli lifecycle <agent_id> --objective '...' --inputs '{}'`.
- Authenticated HTTP: `POST /v1/lifecycle` with `agent_id`, `objective`, optional `inputs`, `deadline_seconds`, `max_corrections` and `max_improvements`.

The lifecycle HTTP endpoint returns 200 only for `status=delivered`; blocked cycles return 502. It accepts 0–2 corrections and 1–5 improvement rounds (default 3). The normal `POST /v1/invoke` endpoint remains available and unchanged.

## Delivery and self-improvement boundaries

`deliver` packages a local result for the caller. It does not publish content, send mail, write repositories, deploy, pay, delete or alter accounts. Those actions continue to require their own separately authorized integration and approval.

`Learn` stores outcomes; it does not rewrite role instructions or automatically promote code. The existing self-improvement governor's fixed benchmarks, regression checks, evidence fingerprints, human approval for protected changes and rollback rules remain authoritative.

The 38-role registry and existing provider/permission boundaries are preserved. GitHub CI runs an opt-in full evidence lifecycle test using actual retrieval from `docs.python.org` and an offline Docker test container; the role provider in that integration test is a scripted fixture, not a live AI model. The Render backend remains opt-in and requires `RENDER_API_KEY` and `RENDER_WORKSPACE_ID` in the host secret manager. A successful CI run does not imply Render was deployed, a hosted provider was connected, or durable production evidence storage was configured.
