# Evidence-driven verification gate

## Purpose

The lifecycle no longer treats a model review verdict as proof. A task can be delivered only when (1) every required acceptance criterion has fresh, trusted evidence for the exact candidate and (2) the independent `code-reviewer` accepts the candidate and evidence. The reviewer cannot override a failed, missing, malformed or stale evidence record.

## Acceptance contract

The `project-manager` must return one JSON object, with no markdown fences, containing:

- `steps`: a non-empty array of execution steps.
- `acceptance_criteria`: a non-empty array of up to 50 criteria.

Each criterion has:

```json
{
  "id": "TEST-01",
  "description": "The regression suite passes",
  "kind": "test",
  "target": "0 failures",
  "required": true
}
```

Criterion IDs must be unique. `kind` is one of `artifact`, `test`, `source` or `measurement`. Every target is a measurable expected result. At least one criterion must be required. Callers may supply an explicit contract in `inputs.acceptance_criteria`; when present, it replaces the planner-generated criteria after the same validation.

Planner instructions require artifact checks for every task, test checks for code or automation, source checks for factual research and source-backed claims, and measurement checks for quantified objectives. The reviewer also inspects whether the contract is sufficient for the original request and flags missing coverage.

## Trusted evidence checker interface

`EvidenceEngine` is deterministic and does not execute arbitrary model-supplied shell commands or accept a model's claim that a test passed. The host may register trusted checkers when constructing `Coordinator`:

```python
Coordinator(
    evidence_checkers={
        "test": run_tests_in_approved_sandbox,
        "source": verify_sources_with_authorized_retriever,
        "measurement": measure_against_domain_rules,
    }
)
```

Each checker receives `(candidate, criterion, context)` and returns a dictionary:

```python
{
    "passed": True,                  # must be a bool
    "actual": "0 failures",           # observed result, not a model assertion
    "expected": "0 failures",         # defaults to criterion.target
    "evidence_ref": "ci://run/123",   # stable log, artifact or source-record reference
    "details": "Exact suite completed",
}
```

A successful record requires an actual value and a non-empty provenance reference. Missing checker configuration yields `unverified`; invalid results and exceptions fail closed. Required unverified or failed checks block delivery. Optional unverified checks remain visible but do not block.

The built-in `artifact` checker only proves that the candidate is non-empty and records its SHA-256 fingerprint. It does not prove factual accuracy, source quality, correctness of calculations or that code works. Test, source and measurement checkers are not configured by default; a host must supply safe, task-appropriate executors. In particular, test execution should use a separately constrained sandbox and source verification should retrieve and inspect the underlying material, not merely check that a URL string exists.

## Freshness and delivery rules

- Every verification creates a new evidence report; reports are not carried forward as proof after refinement.
- The report binds to a SHA-256 fingerprint of the exact deliverable content.
- `WorkflowRunner(evidence_required=True)` independently checks the report fingerprint and required pass counts before it trusts the reviewer's verdict.
- Each Improve → Verify round reruns the configured checkers for that revision.
- Reviewer feedback is retained with the evidence report and feeds the next improvement round.
- A bare `VERDICT: PASS`, no report, a stale fingerprint, missing evidence reference, checker exception or exhausted improvement budget cannot deliver.
- The learning record retains evidence history, candidate fingerprints, criterion status and reviewer feedback for delivered and blocked cycles.

## Operational boundaries

Checkers are trusted host code and must enforce their own least-privilege scope, timeouts, bounded output and provenance rules. Do not pass user credentials in candidate text or evidence context. Do not run untrusted candidate commands directly in the runtime process. The current local scaffold and HTTP API do not automatically configure source retrieval, a test sandbox or domain-specific measurement adapters. A successful mock CI workflow tests the evidence engine; it does not prove a hosted provider or host checker is connected.

The normal invoke endpoint is unchanged. The authenticated lifecycle endpoint and CLI already accept an `inputs` object, so callers can pass `acceptance_criteria` there without widening the HTTP endpoint's top-level fields.
