# Iterative Quality Cycle Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the workflow repeat Improve → independent Verify rounds on the same candidate until the latest version passes or a bounded iteration budget is exhausted.

**Architecture:** Keep initial execution corrections separate from improvement iterations. Once the initial candidate passes review, repeatedly improve the current candidate and independently review that exact version. Only a passing latest candidate may be assigned to `verified_output` and delivered. Expose the improvement-iteration budget through the Python coordinator, CLI and authenticated HTTP endpoint.

**Tech Stack:** Python 3.12, dataclasses, unittest, GitHub Actions.

## Global Constraints

- Preserve the existing Request → Plan → Execute → Verify → Improve → Deliver → Learn lifecycle and 38-role registry.
- Keep initial verification correction retries separate from post-review improvement iterations.
- Default to two improvement iterations, with a bounded supported range of one to four.
- Verify every improved candidate independently; never deliver the last failed candidate.
- A missing, malformed or non-boolean review result fails closed.
- Keep learning and audit provenance for delivered and blocked cycles.
- Do not expand lifecycle delivery into external publishing, messaging, deployment or other privileged actions.

---

### Task 1: Make improvement verification iterative

**Files:**
- Modify: `unexpected_runtime/workflow.py`
- Test: `tests/test_workflow_lifecycle.py`

**Interfaces:**
- `WorkflowRunner(..., max_improvement_iterations: int = 2)`
- `WorkflowResult.improvement_iterations: int`
- Verification history records `iteration=0` for the pre-improvement review and `iteration=1..N` for each improved candidate.

- [ ] **Step 1: Add focused failing tests**

Assert that after an initial PASS, two consecutive improved candidates may FAIL and a third may PASS; the latest candidate alone is delivered. Assert that exhausting the configured iteration budget yields `blocked_verification`, leaves `verified_output` and `delivery` unset, and records the number of improvement iterations.

- [ ] **Step 2: Verify the relevant failure**

Run the repository regression suite through GitHub Actions. Expected: the newly added tests fail because `WorkflowRunner` does not yet accept `max_improvement_iterations`.

- [ ] **Step 3: Implement the minimum behavior**

Validate `max_improvement_iterations` as an integer from 1 through 4. After the first candidate passes review, loop over Improve → Verify on the same candidate. Feed each failed review into the next improve call. Stop on PASS or the configured limit. Record each review and improvement count. Set delivery fields only after PASS.

- [ ] **Step 4: Verify the focused pass**

Run: `python -m unittest tests.test_workflow_lifecycle.WorkflowRunnerTests -v`

Expected: repeated improvement, delivery gating and exhausted-budget tests pass.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m unittest discover -s tests -v`

Expected: all workflow, coordinator, HTTP and existing regression tests pass.

### Task 2: Expose the improvement budget consistently

**Files:**
- Modify: `unexpected_runtime/coordinator.py`
- Modify: `unexpected_runtime/http_api.py`
- Modify: `unexpected_runtime/cli.py`
- Test: `tests/test_workflow_lifecycle.py`

**Interfaces:**
- `Coordinator.run_lifecycle(..., max_improvement_iterations: int = 2)`
- HTTP `POST /v1/lifecycle` optional `max_improvement_iterations` field, default 2, range 1–4.
- CLI `lifecycle --max-improvement-iterations N`, default 2, range 1–4.

- [ ] **Step 1: Add focused integration assertions**

Verify that the coordinator forwards the selected iteration budget, the HTTP endpoint accepts and validates the field, and the CLI passes the option to the coordinator.

- [ ] **Step 2: Verify the relevant failure**

Run the focused integration tests before the implementation. Expected: tests fail on missing parameter/field handling.

- [ ] **Step 3: Implement the minimum wiring**

Validate the budget at the coordinator boundary and HTTP request boundary. Pass it to `WorkflowRunner`. Add the CLI argument and forward it without changing existing defaults or the normal `/v1/invoke` contract.

- [ ] **Step 4: Verify the focused pass**

Run the coordinator lifecycle and HTTP endpoint tests. Expected: values 1 and 4 are accepted; 0, 5, booleans and non-integers are rejected.

- [ ] **Step 5: Run the affected integration check**

Run: `python -m unittest discover -s tests -v`

Expected: all tests pass.

### Task 3: Document, audit and deliver

**Files:**
- Modify: `docs/VERIFIED_WORKFLOW.md`
- Modify: `tests/test_workflow_lifecycle.py`

**Interfaces:**
- Runtime documentation describes default iteration count, bounds, verification history and fail-closed exhaustion behavior.

- [ ] **Step 1: Update lifecycle documentation**

Document that post-improvement review failures repeat Improve → Verify on the same current candidate and that initial execution retries are a separate budget.

- [ ] **Step 2: Verify documentation and interface consistency**

Check Python, HTTP and CLI defaults/ranges against the documentation and tests.

- [ ] **Step 3: Run complete CI checks**

Run: `python -m compileall -q unexpected_runtime`, `python -m unittest discover -s tests -v`, and the existing CLI smoke commands (`status`, `list`, `eval`).

Expected: all CI steps complete successfully.

- [ ] **Step 4: Obtain independent review**

Review the complete PR diff for retry semantics, fail-closed behavior, API compatibility, data leakage and unintended external actions. Fix review findings and rerun affected tests.

- [ ] **Step 5: Deliver**

Leave the change in a reviewed pull request. Do not merge or deploy without a separate verified release decision.
