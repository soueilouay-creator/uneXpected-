# Prompt Intelligence Implementation Plan

**Status:** Approved and implemented in draft PR #19; CI #672 passed for the code candidate. Documentation and integrity-manifest follow-up is awaiting current-head CI.

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox syntax for tracking.

**Goal:** Build a persistent, source-agnostic Prompt Intelligence subsystem that governs prompt sources, rights, versions, specialist mapping, safety evaluation and approved activation through the existing uneXpected runtime.

**Architecture:** Add a domain service backed by the existing StateStore, using additive SQLite/PostgreSQL schema, immutable prompt versions and the existing ApprovalVerifier/PermissionPolicy. Keep the current AI Money Move catalogue as the first idempotent metadata-only seed and preserve the existing authenticated prompt-search/invocation contract.

**Tech Stack:** Python 3.12 runtime, SQLite, PostgreSQL 16, standard-library JSON/HTTP, existing Coordinator/AgentRegistry/PermissionPolicy, unittest, GitHub Actions and the existing single-process Docker image.

**Execution note:** Tests and implementation are present, but the plan's separate red-phase verification (Step 2) was not captured as a distinct CI run for every task and remains unchecked. The green verification evidence is recorded in the PR and CI run references.

## Global Constraints

- Preserve the one Python application, one Coordinator, one API boundary, one shared SQLite/PostgreSQL state layer and 38 canonical roles.
- Do not add a service, database, cache, agent identity, background scheduler or remote source crawler.
- All source material and connector output are untrusted data; they never override system/runtime instructions.
- Unknown/restricted licences are metadata-only. Source bodies require an explicit allowed rights status, evidence and attribution.
- Prompt-level permission scopes are rejected. A prompt may not install tools or elevate a mapped role.
- Ingestion is staging only. Activation must use existing action-bound, one-use host approval for modify_policy.
- Active prompt version remains available while new versions are staged/reviewed.
- Existing /v1/prompts, /v1/prompts/{id}, /v1/invoke and /v1/lifecycle behavior remains compatible.
- No deployment, external connector activation, privileged execution, external message/publish/spend or old-service retirement.

---

### Task 1: Prompt Intelligence domain contract and deterministic evaluator

**Files:**
- Create: unexpected_runtime/prompt_intelligence.py
- Create: tests/test_prompt_intelligence.py
- Create: tests/fixtures/prompt_imports/ sample JSON fixture files
- Modify: unexpected_runtime/prompt_library.py only for reusable title/category/native-instruction helpers if required.

**Interfaces:**
- PromptSourceAdapter protocol: fetch_batch(source_id: str, cursor: str | None = None) -> dict[str, Any]. Adapters return candidate records only; the service always stages them.
- PromptIntelligence(store, agent_registry, permission_policy, catalog_path=None).
- register_source(source: dict, actor: str) -> dict.
- stage_batch(source_id: str, records: list[dict], actor: str) -> dict.
- review_prompt(prompt_id: str, version: int, *, mapped_agent_id: str, rights_evidence_url: str | None, reviewer_note: str) -> dict.
- activation_action_details(prompt_id: str, version: int) -> dict.
- activate_prompt(prompt_id: str, version: int, approval: ApprovalContext) -> dict.
- search_active(query: str = "", category: str | None = None, limit: int = 50, offset: int = 0) -> tuple[list[dict], int].
- get_active(prompt_id: str) -> dict.
- evaluate_prompt(record: dict) -> dict is deterministic and returns checks, risk flags, evaluation ID and SHA-256 digest.

- [x] Step 1: Add failing domain tests

Test metadata-only unknown source acceptance, rejection of a body for unknown/restricted rights, evidence requirements for open/permissioned source text, user-supplied text, exact duplicate idempotency, version staging without active-version replacement, injection-marker rejection, invalid canonical role rejection, and rejection of non-empty prompt permission scopes.

- [ ] Step 2: Verify red

Run: python -m unittest discover -s tests -p 'test_prompt_intelligence.py' -v

Expected: import failure for unexpected_runtime.prompt_intelligence or missing domain methods, with no setup/syntax error.

- [x] Step 3: Implement domain service

Implement typed source/prompt/version records, strict HTTP(S) source URL validation, rights/retention validation, stable source/external IDs, SHA-256 hashing over canonical version data, deterministic evaluator and lifecycle validation. Keep source bodies nullable; never synthesize a body for metadata-only sources. Validate mapped role IDs against AgentRegistry. Reject required_permissions in imported records. New imports create staged candidate versions only.

- [x] Step 4: Verify green

Run the same focused command. Expected: all domain tests pass, with no mutation of an existing active version when a new candidate is staged.

- [x] Step 5: Commit

git add unexpected_runtime/prompt_intelligence.py tests/test_prompt_intelligence.py tests/fixtures/prompt_imports
git commit -m "feat: add governed prompt intelligence domain"

### Task 2: Durable SQLite/PostgreSQL prompt registry

**Files:**
- Create: migrations/003_prompt_intelligence.sql
- Modify: unexpected_runtime/storage.py
- Modify: unexpected_runtime/postgres_storage.py
- Create: tests/test_prompt_intelligence_storage.py
- Modify: tests/test_postgres_storage.py or add tests/test_postgres_prompt_intelligence.py.

**Interfaces consumed:** Task 1 source/prompt/version records.

**Storage methods produced:**
- create_prompt_source(record) -> dict, get_prompt_source(source_id), list_prompt_sources(limit), update_prompt_source(record, expected_status).
- stage_prompt_version(prompt_id, source_id, external_id, version, version_record, expected_candidate_version=None) -> dict.
- get_prompt(prompt_id), get_prompt_version(prompt_id, version).
- list_prompts(status=None, source_id=None, category_id=None, query="", limit=100, offset=0).
- save_prompt_review(prompt_id, version, review, expected_status).
- activate_prompt_version(prompt_id, version, expected_candidate_version) -> dict.
- seed_prompt_catalog(source, rows) -> int — insert-only, one transaction, safe to rerun.

- [x] Step 1: Add failing storage tests

Use temporary SQLite to prove source/prompt/version round trips, duplicate unique constraints, exact candidate version CAS, transaction rollback and persistence after closing/reopening the database. Add PostgreSQL integration coverage using the CI-provided DATABASE_URL and verify migration version 3.

- [ ] Step 2: Verify red

Run: python -m unittest discover -s tests -p 'test_prompt_intelligence_storage.py' -v

Expected: missing StateStore methods/tables; PostgreSQL contract tests also fail until migration 003 exists.

- [x] Step 3: Implement migration and both adapters

Create prompt_sources, prompts, and prompt_versions with foreign keys, unique (source_id, external_id), unique (prompt_id, version), status indexes, JSON metadata columns, nullable body and version hashes. Add equivalent SQLite tables in StateStore._init. Add transactional insert/update/CAS methods to SQLite and PostgreSQL. Advance the Postgres minimum schema check to version 3. Never use production auto-repair or local fallback.

- [x] Step 4: Verify green

Run the focused SQLite tests and PostgreSQL storage test under the CI ephemeral database. Expected: same logical records and state transitions across both adapters, and a repeat migration/seed does not duplicate rows.

- [x] Step 5: Commit

git add migrations/003_prompt_intelligence.sql unexpected_runtime/storage.py unexpected_runtime/postgres_storage.py tests/test_prompt_intelligence_storage.py tests/test_postgres_prompt_intelligence.py
git commit -m "feat: persist governed prompt sources and versions"

### Task 3: Bootstrap, approval-gated lifecycle and invocation integration

**Files:**
- Modify: unexpected_runtime/prompt_intelligence.py
- Modify: unexpected_runtime/http_api.py
- Modify: unexpected_runtime/coordinator.py only if required to append the fixed untrusted-prompt-data guard.
- Modify: tests/test_prompt_library_api.py
- Create: tests/test_prompt_intelligence_api.py
- Modify: tests/test_prompt_intelligence.py.

**Interfaces:**
- The service seeds the existing 1,178-row AI Money Move index once as source aimoneymove-prompt-index, rights unknown, retention metadata_only, and active native rewrites.
- GET /v1/prompt-intelligence/sources.
- POST /v1/prompt-intelligence/sources.
- POST /v1/prompt-intelligence/sources/{source_id}/review.
- POST /v1/prompt-intelligence/import.
- GET /v1/prompt-intelligence/review-queue.
- POST /v1/prompt-intelligence/prompts/{prompt_id}/review.
- POST /v1/prompt-intelligence/prompts/{prompt_id}/activate.
- Existing GET /v1/prompts and prompt detail return active DB-backed records only.
- Existing POST /v1/invoke and POST /v1/lifecycle accept only an active prompt_id whose mapped role equals agent_id.

- [x] Step 1: Add failing API/activation tests

Verify bearer auth, metadata-only source registration, quarantined import, missing-rights rejection, prompt review, activation denial when ApprovalVerifier is absent, denial for wrong action digest/replay/stale version, success with a fake verifier bound to the exact digest, active-only search/detail, role mismatch rejection before provider dispatch, and task source/version/hash persistence.

- [ ] Step 2: Verify red

Run: python -m unittest discover -s tests -p 'test_prompt_intelligence_api.py' -v

Expected: missing Prompt Intelligence routes and service integration, not setup errors.

- [x] Step 3: Implement the API flow

Initialize PromptIntelligence from the existing Coordinator store/registry/permissions. Seed metadata-only catalogue idempotently. Import operations stage only. Review requires an existing AgentRegistry role, evidence, and a passing deterministic evaluation. Activation invokes PermissionPolicy.authorize(..., "modify_policy", approval, action_details=...); digest covers source ID, prompt ID/version, content hash, rights evidence, mapped role and evaluation digest. API must not accept caller-authored reserved task metadata or caller-supplied permission grants.

- [x] Step 4: Verify green

Run the same focused API tests and all prompt-library tests. Expected: no prompt activates without a trusted approval; current AI Money Move 1,178 metadata records remain searchable and usable.

- [x] Step 5: Commit

git add unexpected_runtime/prompt_intelligence.py unexpected_runtime/http_api.py unexpected_runtime/coordinator.py tests/test_prompt_intelligence_api.py tests/test_prompt_library_api.py tests/test_prompt_intelligence.py
git commit -m "feat: gate prompt ingestion and activation through runtime approvals"

### Task 4: Command Center Prompt Intelligence workspace

**Files:**
- Modify: web/index.html
- Modify: web/assets/app.js
- Modify: web/assets/styles.css
- Create: tests/test_prompt_intelligence_ui_contract.py if existing UI checks do not cover the new form IDs/routes.

**Behavior:**
- Keep the existing Prompt Library search/selection view.
- Add a separate Prompt Intelligence administration view with source registration, rights/retention fields, bounded JSON batch import, source list, staged review queue, specialist-role mapping and a read-only activation approval status.
- Source and import forms explain that writes stage records only. Activation button remains disabled without complete review/evaluation and the verified host approval flow.
- Display active/candidate versions separately. Active prompt remains selectable while a newer version is under review.
- Escape all imported titles, source names, URLs and metadata before rendering.

- [x] Step 1: Add failing UI contract checks

Assert the page contains a Prompt Intelligence view, source-registration fields, batch-import field, review queue, mapped-role control and no control claiming that import or review activates a prompt automatically.

- [ ] Step 2: Verify red

Run: python -m unittest discover -s tests -p 'test_prompt_intelligence_ui_contract.py' -v

Expected: missing Prompt Intelligence view/controls.

- [x] Step 3: Implement UI and handlers

Add the view, bind it to authenticated APIs, parse bounded JSON input, show staged outcomes and render approval state. Do not call provider or external connector on source registration/import.

- [x] Step 4: Verify green

Run the UI contract tests and a JavaScript syntax check in CI. Expected: active catalog still works, import UI stages only, and no missing DOM references.

- [x] Step 5: Commit

git add web/index.html web/assets/app.js web/assets/styles.css tests/test_prompt_intelligence_ui_contract.py
git commit -m "feat: add prompt intelligence source and review workspace"

### Task 5: Release evidence, integrity and end-to-end container test

**Files:**
- Modify: .github/workflows/ci.yml
- Modify: FILE_INVENTORY_SHA256.txt
- Modify: README.md, CHANGELOG.md, ARCHITECTURE.md, CAPABILITY_MATRIX.md
- Create: docs/integrations/prompt-intelligence.md
- Modify: tests/test_structure.py.

- [x] Step 1: Add failing release contracts

Assert required migration/service/tests/docs exist, catalogue contains 1,178/15, source rights metadata is metadata-only, and migration history version 3 is present.

- [ ] Step 2: Verify red

Run the focused structure tests. Expected: missing release docs/migration or stale hash.

- [x] Step 3: Add the release evidence

Update docs, version/source provenance, integrity inventory and Docker smoke test to register a source, import a sample, reject unlicensed body content, review/map/evaluate a safe sample, deny activation without approval, and verify active seed data/search/task invocation. Use only deterministic fixtures; no live provider, paid service or outside source retrieval in CI.

- [x] Step 4: Verify green

Run: node --check web/assets/app.js; python -m compileall -q unexpected_runtime; python -m unittest discover -s tests -v; the full GitHub Actions CI. Expected: regression/security tests pass, PostgreSQL migration 003 applies, the SHA-256 inventory matches, the Docker image builds, the real container smoke verifies health/UI/auth/38 roles, active prompt catalogue/source/review-queue APIs and task invocation, and CLI smoke passes. Source registration/import/review and fail-closed activation are additionally covered by authenticated API regression tests.

- [x] Step 5: Commit

git add .github/workflows/ci.yml FILE_INVENTORY_SHA256.txt README.md CHANGELOG.md ARCHITECTURE.md CAPABILITY_MATRIX.md docs/integrations/prompt-intelligence.md tests/test_structure.py
git commit -m "docs: verify prompt intelligence release contract"

- [x] Step 6: Open a draft PR

Open a draft PR targeting feat/v8.1-durable-traces and record exact base/head SHA, CI run, changed paths, source rights policy and release blockers. Keep it draft until independent review and all required upstream branches are reconciled.

---

## Release sequencing and gates

1. PR #11 remains the v8 foundation candidate on main; it is not merged.
2. PR #12 (advanced skills) remains stacked on #11 and is still a draft dependency.
3. PR #15 (durable traces/MCP gateway/subagents) remains stacked on #12. Its CI run #634 passed on head `da89926b965dc62fa72800bf909c844692a1b4ef`, but the PR remains draft and must be reviewed/merged in the agreed order.
4. Canonical Prompt Intelligence candidate is PR #19 on `feat/v8.1-prompt-intelligence-v3`, based directly on the latest PR #15 branch commit above. The Command Center UI, source rights review, import, queue, role mapping, approval preparation and active catalogue are included. CI #672 passed on code head `c7cde66e0c96bf89e0169211c7b31ff39aefd917`; documentation/inventory updates after that run require current-head CI before merge.
5. PR #16 (static Prompt Library) and PR #17 (earlier diverged Prompt Intelligence branch) are closed as superseded. PR #18 was a closed temporary CI mirror. Do not merge any of these older branches or duplicate catalogue paths.
6. PR #13 is a separate overlapping MCP-boundary proposal and needs consolidation review rather than an automatic parallel merge. Keep one active MCP execution boundary only.
7. Merge only after current-head CI, independent code review, clean diff and explicit upstream merge order. Keep PR #19 draft until those gates are met.
8. Render deployment requires the owner to select the workspace. A green GitHub CI run is not a deployed service, live provider result, durable backup/restore proof or production approval configuration.

## Unresolved release decisions

- Which Render workspace to use for the production/preview deployment must be selected by the owner before any Render mutation.
- Whether PR #13's independent MCP boundary is superseded by PR #15's gateway must be resolved in code review before merge; do not keep two active MCP execution paths.
- Production activation of policy-changing prompt approvals remains off until the existing host approval verifier and trusted reviewers are configured and a live approval/replay test passes.
