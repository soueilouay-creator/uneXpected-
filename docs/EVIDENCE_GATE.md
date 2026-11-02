# Evidence-driven verification gate

## Purpose

The lifecycle no longer treats a model review verdict as proof. A task can be delivered only when (1) every required acceptance criterion has fresh, trusted evidence for the exact candidate and (2) a separately configured reviewer provider accepts the candidate and evidence. A role name alone is not proof of provider independence. The reviewer cannot override a failed, missing, malformed or stale evidence record.

## Acceptance contract

Production lifecycle review requires a distinct reviewer provider. The coordinator refuses to run a lifecycle review if no separate provider route is configured and rejects reuse of the same provider object. For AI Studio, configure `UNEXPECTED_REVIEW_PROVIDER=ai_studio_gateway` with a different `UNEXPECTED_REVIEW_GATEWAY_MODE` (for example, primary `openai`, reviewer `claude`). Alternatively configure `openai_compatible` with a separate endpoint/model/key. If the primary route is `both` on the same gateway, use a separate reviewer endpoint instead of reusing either model route. Authenticated status reports the reviewer route without exposing credentials.

For the AI Studio gateway reviewer route, the coordinator budgets the complete reviewer prompt against the gateway's 15,000 UTF-16-code-unit limit. Long candidate text is sent as a bounded excerpt together with the full candidate SHA-256 and original UTF-16 length; verbose test output and retrieved source excerpts are shortened. Criterion IDs, required/status fields, evidence references and the evidence summary are retained. The reviewer must not claim to have inspected omitted candidate content. Gateway provider/model/status metadata is stored separately on the task result and never prefixed to model text, preserving planner JSON and reviewer verdict parsing.

The `project-manager` must return one JSON object, with no markdown fences, containing:

- `steps`: a non-empty array of execution steps.
- `acceptance_criteria`: a non-empty array of up to 50 criteria.

Each criterion has:

```json
{
  "id": "TEST-01",
  "description": "The regression suite passes",
  "kind": "test",
  "profile": "evidence-engine",
  "target": "0 failures",
  "required": true
}
```

Criterion IDs must be unique. `kind` is one of `artifact`, `test`, `source` or `measurement`. Every target is a measurable expected result. At least one criterion must be required. When the Docker or Render test backend is enabled, every `test` criterion must include `profile: "evidence-engine"`; other profile names are rejected. With other checker configurations the profile field is optional. Callers may supply an explicit contract in `inputs.acceptance_criteria`; when present, it replaces the planner-generated criteria after the same validation.

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

The built-in `artifact` checker only proves that the candidate is non-empty and records its SHA-256 fingerprint. It does not prove factual accuracy, source quality, correctness of calculations or that code works.

### Isolated test execution

The runtime supports two explicitly selected test backends:

- `UNEXPECTED_TEST_EXECUTOR=docker` for CI or a self-hosted host with Docker.
- `UNEXPECTED_TEST_EXECUTOR=render-sandbox` for a disposable Render Sandboxes microVM.

Both execute only the fixed `evidence-engine` profile. Every `test` criterion for these backends must include the required `profile` field set to `evidence-engine`; omitting it blocks the check. Arbitrary commands are not accepted. The profile consists of exactly four checked-in files: `tests/test_evidence_engine.py`, `unexpected_runtime/__init__.py`, `unexpected_runtime/evidence.py` and `unexpected_runtime/workflow.py`. Every staged file has a mandatory SHA-256 entry in the profile's complete `trusted_files` manifest; missing, extra, malformed or mismatched digests block staging. The host hashes each file and stages the same verified byte buffer, then records the sorted path-to-digest manifest and its canonical SHA-256 in the measured evidence record. The `docker-test://` or `render-sandbox://` evidence reference hashes that complete measured record, including the profile-manifest digest, and the checker independently recomputes both the manifest and reference before accepting PASS. This profile runs a fixed checked-in regression suite; it does not execute the candidate deliverable. Therefore, a passing profile proves that the pinned evidence-engine tests passed against the four pinned files in the isolated backend, not that candidate code was executed or tested. Criteria that require executing the candidate are unsupported unless a separate, candidate-specific trusted checker is implemented and configured. The Docker backend requires an immutable image digest and runs with `--network=none`, a read-only root, dropped capabilities, no-new-privileges, a non-root UID, memory/CPU/PID limits and a guest timeout. Host stdout/stderr are drained incrementally into a fixed-size tail buffer, so output volume does not increase host memory use. The Render backend creates an ephemeral microVM with `network_policy="deny-all"`, uploads only the four fixed profile files after every file digest has been verified, applies a guest timeout, and explicitly terminates the sandbox. A failed or unconfirmed cleanup blocks PASS.

Render configuration is held on the host only. Before enabling the backend, install the pinned runtime dependencies on the host with `python -m pip install --disable-pip-version-check -r requirements.txt`; this installs the Render SDK from `requirements.txt`. Then set `RENDER_API_KEY`, `RENDER_WORKSPACE_ID` and `UNEXPECTED_TEST_EXECUTOR=render-sandbox` in the runtime host's secret manager. The token is used only by the host SDK client; it is never injected into the sandbox. `UNEXPECTED_TEST_SANDBOX_TIMEOUT_SECONDS` bounds the microVM lifetime. Status reports the backend as blocked when the SDK is unavailable. The GitHub Actions workflow uses a Docker image resolved to an immutable digest for its end-to-end isolated test run; this is a CI container backend, not evidence that the Render microVM service has been enabled.

### Trusted source retrieval

Set `UNEXPECTED_SOURCE_ALLOWED_DOMAINS` to a comma-separated list of exact hostnames, for example `docs.python.org`. Wildcards, IP literals, single-label/internal hostnames, non-HTTPS URLs, credentials, non-443 ports, queries/fragments, redirects and non-public DNS answers are rejected. DNS is resolved and validated before the TCP connection; the connection is pinned to a validated public address while TLS hostname verification remains enabled. Requests and responses have a single absolute retrieval deadline and byte bounds, including streamed response-body reads; a slow-trickling peer cannot reset the full timeout on each chunk. Compressed/non-text responses are rejected, and only bounded HTML/plain-text/JSON excerpts are retained. The evidence record includes the original URL, title, content type, retrieval time, byte count, raw-body SHA-256 and excerpt. The source retriever runs in the trusted host, not inside the network-disabled test sandbox.

The source adapter's PASS means that allowlisted source material was actually retrieved and fingerprinted; it does not mean that the source proves the candidate's claims. The independent reviewer receives the retrieved title/excerpt and must assess relevance, support and contradictions. When the independent reviewer uses the AI Studio gateway, source excerpts and test output tails are shortened to fit the gateway's total prompt budget; the reviewer receives the complete evidence IDs, statuses and references and a bounded candidate excerpt with the full candidate SHA-256 and original length. It must not claim to have reviewed content omitted from that excerpt. A source URL string by itself is never evidence. Default limits are three sources, 262,144 bytes per document, 8 seconds per request and 2,400 excerpt characters per source; host configuration can tune within the adapter's validated bounds.

Test, source and measurement checkers are not active unless the host configuration is complete. Incomplete test configuration is exposed as `blocked`; absent configuration is `not configured`. Either state leaves required criteria unverified and blocks delivery. The authenticated `GET /v1/status` response exposes `test_backend`, `source_backend` and the registered `evidence_checkers`; it never returns secret values.

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

The authenticated `GET /v1/status` response lists configured `evidence_checkers` so operators can see which evidence kinds are actually executable. By default, only `artifact` is available; absent test/source/measurement adapters are not represented as active.

The normal invoke endpoint is unchanged. The authenticated lifecycle endpoint and CLI already accept an `inputs` object, so callers can pass `acceptance_criteria` there without widening the HTTP endpoint's top-level fields.
