# Operational Evidence Adapters Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect uneXpected's evidence gate to a network-restricted test microVM and a trusted, provenance-preserving source retriever, then execute the complete lifecycle against a real documented task.

**Architecture:** Add host adapters that are selected explicitly from environment configuration. The production test adapter uses Render Sandboxes (ephemeral microVM, no outbound network, bounded lifetime, explicit source-file staging); GitHub CI uses an equivalently restricted Docker backend for live adapter integration tests. The source adapter performs direct HTTPS retrieval only for configured allowlisted domains, pins DNS results to public IPs, refuses redirects/private addresses, bounds bytes/time/count, extracts text and hashes it. Both adapters return measured evidence with references; the existing deterministic gate and independent reviewer remain mandatory.

**Tech Stack:** Python 3.12, stdlib `asyncio`, `http.client`, `ssl`, `socket`, `ipaddress`, `html.parser`, Docker CLI in GitHub Actions, Render Python SDK 1.6.0 for managed Sandboxes, GitHub Actions CI.

## Global Constraints

- Do not run arbitrary model/user-supplied shell commands. Test profiles and commands are fixed in code and selected by a bounded profile ID.
- Test execution runs in a disposable isolated environment with explicit resource/time bounds and network egress denied.
- Render API credentials remain only in the host secret store. Never upload Render tokens or unrelated environment variables into the sandbox.
- Source retrieval is HTTPS-only, exact-host allowlisted, DNS-pinned to public addresses, non-redirecting, size-bounded, timeout-bounded and content-type constrained.
- Model-authored assertions do not constitute test evidence or source evidence.
- Every evidence report remains fingerprint-bound to the exact candidate and must pass alongside independent review.
- Preserve the 38-role registry, existing permissions, approvals, provider behavior and local delivery boundary. Do not deploy, merge or change live service configuration in this task.
- Keep evidence checkers optional and fail-closed when configuration is absent. Expose active adapters in authenticated runtime status without exposing secrets.

---

### Task 1: Trusted, SSRF-resistant HTTPS source retrieval

**Files:**
- Create: `unexpected_runtime/source_retrieval.py`
- Create: `tests/test_source_retrieval.py`
- Modify: `unexpected_runtime/evidence.py`
- Modify: `tests/test_evidence_engine.py`
- Modify: `.env.example`

**Interfaces:**
- Produces `TrustedSourceRetriever(allowed_domains, timeout_seconds=8, max_bytes=262144, max_sources=5)`.
- Produces callable `SourceEvidenceChecker(retriever)` compatible with `EvidenceEngine`.
- Produces `source_retriever_from_env()`; no allowlist means no checker is registered.
- Source evidence returns title, exact URL, content type, retrieval time, SHA-256 and bounded excerpt for independent review.

- [ ] **Step 1: Add focused failing tests**
  - Allowed HTTPS host resolves only to public IPs and a successful HTML response yields extracted text, title, SHA-256 and a stable `source-bundle://` evidence reference.
  - Reject HTTP, credentials, non-443 ports, fragments, unallowlisted hosts, IP literals, private/loopback/link-local DNS answers, mixed public/private DNS answers and redirects.
  - Reject oversized bodies, unsupported content types, non-identity content encodings, empty content and source counts above the limit.
  - `source` criteria preserve retrieved excerpts in `actual`; missing source refs and partial failures do not produce PASS.
  - A real integration test is opt-in and fetches the official Python `unittest` documentation from `docs.python.org`.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m unittest tests.test_source_retrieval -v`
  - Expected: import/attribute failures because the retriever and checker are not implemented.

- [ ] **Step 3: Implement the minimum behavior**
  - Use stdlib HTTPS with TLS hostname validation and a connection pinned to a prevalidated public DNS answer.
  - Set exact host allowlist matching, disable redirects by accepting only HTTP 200, request identity encoding, cap the response at `max_bytes + 1`, and parse only HTML/plain text/JSON.
  - Strip script/style/noscript/svg/iframe content from HTML and normalize whitespace; retain only bounded excerpts.
  - Preserve only the optional `profile` field for test criteria in `EvidenceEngine.validate_criteria`; do not weaken existing evidence validation.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m unittest tests.test_source_retrieval tests.test_evidence_engine -v`
  - Expected: all source and evidence-engine tests pass; security rejection cases remain fail-closed.

- [ ] **Step 5: Run the affected integration check**
  - Run: `python -m compileall -q unexpected_runtime tests`
  - Expected: zero compilation errors.

- [ ] **Step 6: Commit the passing deliverable**
  - Commit message: `feat: add trusted allowlisted source retrieval`.

### Task 2: Isolated test executors and host configuration

**Files:**
- Create: `unexpected_runtime/test_execution.py`
- Create: `tests/test_test_execution.py`
- Create: `requirements.txt` (pin `render==1.6.0`)
- Modify: `unexpected_runtime/coordinator.py`
- Modify: `.env.example`

**Interfaces:**
- Produces fixed test profile `evidence-engine` mapped only to `python -m unittest discover -s tests -p test_evidence_engine.py -v`.
- Produces `RenderSandboxTestExecutor(workspace_root, workspace_id, timeout_seconds=300)`, selected with `UNEXPECTED_TEST_EXECUTOR=render-sandbox`; uses Render SDK 1.6.0, an ephemeral sandbox, `network_policy="deny-all"`, bounded readiness/exec/cleanup, and an explicit four-file profile allowlist.
- Produces `DockerTestExecutor(workspace_root, image_digest, timeout_seconds=180)`, selected only in CI with `UNEXPECTED_TEST_EXECUTOR=docker`; requires an immutable image digest, no network, read-only root, non-root user, dropped capabilities, no-new-privileges, PID/memory/CPU/time bounds and an explicit source-file staging allowlist.
- Produces `test_executor_from_env()` and environment-based evidence-checker wiring. Explicit constructor-injected checkers continue to take precedence over environment discovery.
- Both executors return `passed`, exit code, parsed test count, bounded output and a sandbox/container provenance reference. Cleanup failure fails the evidence check.

- [ ] **Step 1: Add focused failing tests**
  - Reject unknown profiles, mutable image tags, missing Docker, absent workspace files and invalid timeout bounds.
  - Verify Docker argv contains `--network none`, read-only root, dropped capabilities, no-new-privileges, non-root user and resource limits; ensure no shell and no arbitrary command from the criterion is executed.
  - Verify Render SDK call creates a disposable sandbox with deny-all egress, uploads only the explicit profile files, runs the fixed test command, requires an exit event and terminates on both success and failure.
  - Verify missing Render API key/workspace or SDK returns an unconfigured/failed-closed state without leaking secrets.
  - Verify the evidence checker reports PASS only for exit code zero, a parsed test result and confirmed cleanup.
  - Verify Coordinator registers only configured test/source adapters and status names the active backend without exposing credentials.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m unittest tests.test_test_execution -v`
  - Expected: import/attribute failures because the executors are not implemented.

- [ ] **Step 3: Implement the minimum behavior**
  - Build a staging directory from only the static profile file list; reject symlinks and missing files. Do not copy the workspace wholesale.
  - Keep test profile argv constant in code. Never interpolate request text into shell commands.
  - For Render, use the public SDK and a per-run microVM. Keep the Render API key in the host only; do not place it in sandbox env.
  - For CI Docker, require a digest and enforce a strict isolated container configuration.
  - Wire environment adapters into Coordinator only when the corresponding configuration is complete. Include `test_backend` and `source_backend` in status; never include token values.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m unittest tests.test_test_execution tests.test_source_retrieval tests.test_evidence_engine -v`
  - Expected: all adapter contract and fail-closed tests pass.

- [ ] **Step 5: Run the affected integration check**
  - Run: `python -m compileall -q unexpected_runtime tests`
  - Expected: zero compilation errors.

- [ ] **Step 6: Commit the passing deliverable**
  - Commit message: `feat: add isolated Render and CI test executors`.

### Task 3: Complete lifecycle integration and real-source smoke test

**Files:**
- Create: `tests/test_evidence_live_lifecycle.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `docs/EVIDENCE_GATE.md`
- Modify: `docs/VERIFIED_WORKFLOW.md`
- Modify: `tests/test_structure.py`
- Modify: `FILE_INVENTORY_SHA256.txt`

**Interfaces:**
- The native `Coordinator.run_lifecycle(...)` uses both configured adapters without changing the public lifecycle API.
- A deterministic provider fixture drives planner, specialist, reviewer and improvement calls; it does not impersonate a live model.
- The real smoke objective is to prepare a short explanation of Python `unittest` test discovery, retrieve the official Python documentation, run uneXpected's evidence-engine tests inside the no-network test sandbox, improve the report and re-run both checks before delivery.
- The live integration test is enabled only by an explicit CI environment flag; it uses Docker in CI for isolated test execution and live HTTPS retrieval from `docs.python.org`. The Render SDK backend is contract-tested and remains opt-in until `RENDER_API_KEY` and `RENDER_WORKSPACE_ID` exist in the runtime secret store.

- [ ] **Step 1: Add the focused failing integration test**
  - Assert the full sequence reaches `delivered` only after two current evidence reports and two reviewer PASS verdicts.
  - Assert both test runs have exit code zero and both source retrievals have a real SHA-256/provenance record.
  - Assert evidence references and candidate fingerprints differ or are freshly generated for each verification round.
  - Assert missing source configuration, failed test execution, reviewer FAIL, stale evidence or cleanup failure blocks delivery.
  - Assert the sandbox never receives network access and source retrieval occurs in the trusted host adapter.

- [ ] **Step 2: Verify the relevant failure**
  - Run: `python -m unittest tests.test_evidence_live_lifecycle -v`
  - Expected: the live integration test is skipped without explicit opt-in; the configured integration test fails before the adapter wiring is complete.

- [ ] **Step 3: Implement the minimum CI and documentation wiring**
  - CI pulls a versioned official Python image, resolves its immutable registry digest for that run, exports the digest, and enables the Docker-backed full lifecycle smoke.
  - CI enables source retrieval only for exact `docs.python.org`.
  - Preserve the normal regression suite and all existing CLI smoke tests.
  - Document how operators set Render secrets in the host secret manager; never set a placeholder or ask for the secret in chat.

- [ ] **Step 4: Verify the focused pass**
  - Run: `python -m unittest tests.test_evidence_live_lifecycle -v` with the CI opt-in environment.
  - Expected: one completed lifecycle, two successful isolated test executions, two real official-source retrievals, two independent review passes and a delivered result.

- [ ] **Step 5: Run the full integration check**
  - Run: `python -m compileall -q unexpected_runtime tests && python -m unittest discover -s tests -v`
  - Expected: zero failures; only explicitly optional tests may skip. GitHub Actions package integrity and CLI smoke tests also pass.

- [ ] **Step 6: Commit the passing deliverable**
  - Commit message: `test: verify evidence-gated lifecycle with live adapters`.

---

## Unresolved external operational decision

The Render service currently has no verified Render Sandbox API credential available through the connected service metadata. The code can be integrated and contract-tested now, but live microVM creation on the hosted Render service requires the owner to add `RENDER_API_KEY` and `RENDER_WORKSPACE_ID` through Render's secret settings. The key must remain in the host environment; it must not be shared in chat or injected into the sandbox. No deploy, Render environment mutation, or PR merge is included in this plan.
