# uneXpected v8 Unified System Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate uneXpected's governed runtime, Node gateway, web interface and mobile workspace into one canonical, owner-controlled application without losing existing workflow definitions or user data.

**Architecture:** Use the current Python-runtime repository as the canonical source, preserve its latest main-branch code, and import the Node gateway/PWA into that repository. Run Node as the public HTTP application and Python as a loopback-only governed runtime in one supervised Docker deployment. Use Neon Free PostgreSQL as the shared persistent data plane, only while its $0 quota is valid; local-first IndexedDB remains recoverable and syncs additively.

**Tech Stack:** Node.js 22, Python 3.12, SQLite for isolated tests only, PostgreSQL/psycopg, Docker, Render Free, Neon Free, GitHub Actions.

## Global Constraints

- Canonical source baseline is `main` at `59deef5e49208c01d03ccfc6d2e162db54309235`; do not use the four-commits-behind integration branch as the basis.
- Preserve all 38 agent IDs and source manifests, latest `run_lifecycle`, workflow profiles, skills, governance, CI tests and current phone PWA features.
- No paid infrastructure and no unapproved provider spend.
- No service shutdown/deletion or live cutover until all gates pass.
- Never print or commit secrets; use host secret manager and a runtime-generated internal loopback token.
- Keep privileged external operations disabled. GitHub PR review approval on its own is not treated as sufficient until persistent transactional one-use storage and independent reviewer validation work in the deployed runtime.
- Preserve existing phone IndexedDB records; import/sync is additive and versioned.
- Never fallback from an unavailable shared database to ephemeral filesystem writes.
- Report each task as created, locally/CI tested, deployed, live verified, migrated or blocked according to evidence.

---

### Task 1: Preserve and import AI Studio source into the canonical repository

**Files:**
- Create in canonical repo: `server.js`, `app.js`, `openrouter-ui.js`, `mobile-assets.mjs`, `taaft-integration.mjs`, `source.tar.gz.b64`
- Create: `mobile-assets.parts/*`, `mobile-release/*`, `mobile/*`, `test/*`, `docs/MOBILE_COMPANION.md`, `docs/TAAFT_MCP_INTEGRATION.md`
- Create: `docs/specs/2026-10-31-phone-three-model-workspace-design.md`
- Update: `README.md`, `SOURCE_MANIFEST.md`, `FILE_INVENTORY_SHA256.txt`
- Test: all copied Node test files under `test/`

**Interfaces:**
- Preserve current Node exports and HTTP routes, including `/health`, `/orchestrate`, `/test-provider`, `/mobile/`, and UI static assets.
- Preserve current PWA IndexedDB schema and backup functions as the initial import surface.

- [ ] **Step 1: Add source-manifest assertions** that list expected AI Studio files and source revision.
- [ ] **Step 2: Verify the test fails** when any required UI/gateway asset is missing.
- [ ] **Step 3: Copy the AI Studio files byte-for-byte** from its reviewed main commit into the v8 branch; do not unpack/modify PWA code during the initial transfer.
- [ ] **Step 4: Run Node tests** using `node --test test/*.test.mjs`.
- [ ] **Step 5: Run Python regression tests** using `python -m unittest discover -s tests -v`.
- [ ] **Step 6: Record source commit IDs and hashes** in the migration manifest.

### Task 2: Add a supervised internal runtime and unified public API

**Files:**
- Create: `Dockerfile`, `requirements-runtime.txt`, `runtime-supervisor.mjs`
- Modify: `server.js`, `unexpected_runtime/http_api.py`
- Create: `test/unified-runtime.test.mjs`, `tests/test_unified_runtime_contract.py`

**Interfaces:**
- Python process: loopback-only `127.0.0.1:8765`, token supplied only in child process environment.
- Node public routes: `POST /v1/lifecycle`, `POST /v1/invoke`, authenticated with the existing owner token and forwarded to the loopback runtime using the internal token.
- Public `GET /health`: reports both gateway and runtime readiness; no key/token values.
- Child readiness: internal `GET /health`; internal calls use bounded timeout and do not follow redirects.

- [ ] **Step 1: Add failing Node tests** for child not-ready, runtime crash, unauthorized external request and lifecycle proxy.
- [ ] **Step 2: Confirm failures** against the unmodified public server.
- [ ] **Step 3: Add supervisor** that generates an internal token per container start, starts Python with loopback bind and fixed private port, waits with bounded retries, starts Node only after readiness, and exits the container if either required process dies.
- [ ] **Step 4: Add proxy routes** that accept only documented non-privileged fields and never accept approval claims or permission scopes.
- [ ] **Step 5: Make `/health` fail unhealthy** if the runtime cannot be reached; continue reporting `privileged_actions: fail-closed`.
- [ ] **Step 6: Run focused Node/Python tests**, then the full existing suites.

### Task 3: Move runtime state to shared PostgreSQL

**Files:**
- Create: `unexpected_runtime/postgres_storage.py`, `unexpected_runtime/migrations/001_initial.sql`
- Modify: `unexpected_runtime/coordinator.py`, `unexpected_runtime/storage.py`, `requirements-runtime.txt`, `.env.example`
- Test: `tests/test_postgres_storage.py`, `tests/test_storage_backend_selection.py`

**Interfaces:**
- `UNEXPECTED_DATABASE_URL` selects PostgreSQL; SQLite remains available only for deterministic local tests when no production database URL is set.
- PostgreSQL backend must implement the same `StateStore` methods consumed by `Coordinator`.
- Migrations run transactionally and record applied version in `schema_migrations`.
- Database connection failure in hosted mode prevents runtime startup/readiness; no ephemeral write fallback.

- [ ] **Step 1: Add backend-contract tests** for queue, event log, per-agent memory, knowledge, idempotency, outcomes, proposals, versions, baselines and capabilities.
- [ ] **Step 2: Verify Postgres backend tests fail** because the backend is absent.
- [ ] **Step 3: Implement PostgreSQL methods and migrations** with parameterized statements, constraints, atomic idempotency writes and transactional rollback.
- [ ] **Step 4: Test restart persistence, uniqueness, transaction rollback, concurrent idempotency and migration re-run.**
- [ ] **Step 5: Run all Python unit tests** and a Neon Free integration smoke test without echoing its connection string.
- [ ] **Step 6: Record quota, backup/export and restore behavior** and add an alert/status for suspended or exhausted database compute.

### Task 4: Preserve and synchronize phone workspace data

**Files:**
- Create: `unexpected_runtime/workspace_store.py`, `unexpected_runtime/migrations/002_workspace.sql`
- Modify: `unexpected_runtime/http_api.py`, `server.js`, `mobile-release/app.js`, mobile source bundle files as necessary.
- Test: `tests/test_workspace_sync.py`, `test/mobile-workspace-sync.test.mjs`

**Interfaces:**
- Authenticated `GET /workspace/export` returns a schema-versioned snapshot.
- Authenticated `POST /workspace/import` accepts a versioned snapshot and returns inserted/updated/conflict counts.
- Import is additive by stable record ID; conflicting local/server versions are preserved as conflict copies, not silently overwritten.
- Local-only offline operation and manual JSON backup export/import remain available.

- [ ] **Step 1: Add failing tests** for additive import, duplicate ID, changed same-ID record, malformed payload and offline behavior.
- [ ] **Step 2: Verify failures** before adding sync code.
- [ ] **Step 3: Add database-backed workspace records** with device/source metadata and deterministic conflict handling.
- [ ] **Step 4: Add opt-in first sync** after owner authentication and preserve original IndexedDB records.
- [ ] **Step 5: Test backup/export/restore round-trip** and make sure restore no longer silently destroys the only copy.
- [ ] **Step 6: Run full PWA and runtime suites.**

### Task 5: Unified deployment, migration verification and cutover

**Files:**
- Modify: `Dockerfile`, `render.yaml`, `.github/workflows/ci.yml`, `README.md`, `DEPLOY.md`, `ARCHITECTURE.md`, `docs/RUNTIME_CONNECTIVITY.md`
- Create: `docs/UNIFIED_V8_CUTOVER.md`, `docs/ROLLBACK_V8.md`, `UNIFIED_MIGRATION_MANIFEST.json`

**Interfaces:**
- One public Render service points to the canonical v8 branch/repository.
- One Neon Free database is the shared durable source of truth.
- Health verifies Node gateway and internal Python runtime; protected endpoint smoke tests require owner token.
- Existing Render services remain untouched until the checklist is complete.

- [ ] **Step 1: Add CI jobs** for Python tests, Node tests, source-manifest verification and Docker build.
- [ ] **Step 2: Verify branch CI passes** and the unified image builds.
- [ ] **Step 3: Provision only a $0 Neon Free project**, capture connection URL directly into Render's secret store without exposing it in logs or chat, and test DB connectivity.
- [ ] **Step 4: Create a new Render Free test service** from this branch with auto-deploy initially disabled; deploy and verify health, auth, lifecycle mock, provider smoke test (only if no paid route is invoked), DB restart persistence and memory budget.
- [ ] **Step 5: Inventory and export old Python SQLite data where possible; import only after count/hash reconciliation.** Preserve phone workspace exports and compare IDs/counts.
- [ ] **Step 6: Perform a controlled cutover** only after all success criteria pass. Keep the old endpoints as rollback for an agreed observation window.
- [ ] **Step 7: Retire old services only through supported Render controls.** If the connected host has no service delete/suspend action, provide the exact dashboard actions and do not imply they were completed.

## Unresolved externally observable decisions

- The phone workspace is currently local-first and single-device. The initial sync design keeps local records and makes the server a copy; cross-device conflict merge behavior requires tests before it is promoted to default.
- Free Neon compute can pause when quotas are exhausted; the app will report unavailable and fail closed rather than pay or write to ephemeral local storage.
- Render Free may not have sufficient memory for two processes in one container. If measured memory exceeds safe limits or the service becomes unstable, stop cutover and keep a single command center with a separately isolated internal execution service; do not mask the resource constraint.
