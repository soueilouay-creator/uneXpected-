# uneXpected v8 Unified Cutover Checklist

**Status:** Test deployment in progress. Do not cut over production traffic until every required gate below is evidenced.

## Current source and deployment identity

- Canonical repository: `soueilouay-creator/uneXpected-`
- Canonical source baseline: the repository `main` branch used to create `feature/unified-v8-consolidation`.
- Feature branch contains the Node gateway, provider adapters, mobile workspace, Python runtime, PostgreSQL backend and supervised-container work.
- New Render test service: `unexpected-v8-unified-test` in Frankfurt.
- Shared data project: Neon Free, `unexpected-v8-unified`, PostgreSQL 17, Frankfurt.
- Existing Render services are rollback sources and must stay available until production cutover is separately authorized and verified.

## Required gates

### Source and code

- [x] Preserve current 38-role registry and canonical role specifications.
- [x] Preserve latest `run_lifecycle` and seven-stage workflow.
- [x] Import reviewed Node gateway, provider routing, TAAFT read-only adapter and phone PWA release.
- [x] Preserve the mobile asset archive SHA-256 verification.
- [x] Python regression CI passes on the v8 branch.
- [x] Node private-proxy contract CI passes on the v8 branch.
- [x] Phone/gateway integration and Docker image build CI passes on the v8 branch.
- [ ] Human review of draft PR #10 and merge into `main`.

### New service

- [x] Create separate v8 Render Free test service; keep previous services unchanged.
- [x] Create Neon Free PostgreSQL project; verify PostgreSQL 17 responds.
- [ ] Verify the new Render deploy completes and stays running.
- [ ] Set Render health check to `/health` in service settings.
- [ ] Verify public `/health` returns 200 with runtime version, 38 agents and `storage_durable=true`.
- [ ] Verify authenticated `/v1/status` returns current runtime status.
- [ ] Verify one harmless deterministic-mock `/v1/lifecycle` task completes through all seven stages.
- [ ] Verify Node and Python use only loopback between processes; no second public runtime endpoint.
- [ ] Measure service memory/cold start; confirm two supervised processes fit Render Free without restart or out-of-memory failure.

### Providers and integrations

- [ ] Transfer OpenAI, Anthropic and optional OpenRouter credentials from the old service to the new service through Render's private environment settings; do not copy secrets into Git or ChatGPT.
- [ ] Change `UNEXPECTED_PROVIDER` from `mock` to `ai_studio_gateway` only after credentials are configured.
- [ ] Run an explicitly authorized low-cost live OpenRouter test and record actual returned model/provider.
- [ ] Run one harmless real-provider lifecycle invocation and verify the runtime rejects mock/fallback provenance where a live primary result is required.
- [ ] Inventory other external integrations. A ChatGPT connector is not automatically an app-side authorization; each new adapter needs its own scoped server credential and tests.

### Data preservation

- [ ] Determine whether the old Render Python service still has a recoverable SQLite database; the current management connector cannot download its ephemeral filesystem.
- [ ] If an old SQLite backup is obtained, run `migrate_sqlite_to_postgres.py` against an empty migration target and retain row-count + per-table hash report.
- [ ] Export each device's local IndexedDB workspace from the phone PWA or use its manual JSON backup before retiring the old service.
- [ ] Use the new phone **Sync workspace** control to copy projects, conversations, memories and improvement ideas to the shared database.
- [ ] Reconcile inserted/duplicate/conflict counts and verify that local records remain intact.
- [ ] Perform a database backup/export and restore drill.
- [ ] Verify database compute quota behavior and application fail-closed handling.

### Security

- [x] Internal runtime bearer token is generated per container start and not exposed in the public app.
- [x] Public API rejects permission/approval claims and unknown fields for invocation.
- [x] Runtime's privileged action routes remain unavailable/fail-closed.
- [ ] Verify owner token rotation and provider secret presence in Render without revealing values.
- [ ] Verify approval replay storage with concurrent duplicate-consume test on PostgreSQL and independent authenticated reviewer identity.
- [ ] Keep consequential execution disabled until transactional approval, action-digest binding, expiry, distinct approver, replay protection, protected repository rules and deployed tests are all confirmed.

## Current known blockers

1. Old Render Python service SQLite state was not exported; there is no evidence that its current database was empty or migrated.
2. Phone IndexedDB records remain on each user's device until the new sync action is performed.
3. Provider secrets cannot be read through the current Render management connector; they must be transferred privately by the owner.
4. Render service health-check settings are not exposed by the current service-management action; set `/health` in the Dashboard.
5. Render Free sleeps after idle and has ephemeral filesystem; Neon Free compute can suspend at quota limits. These are availability constraints, not reasons to enable paid plans.
6. The first test deployment requires verification after the runtime state-directory fix; code CI success alone does not prove Render health.

## Cutover rule

Only after all required gates pass:

1. Keep the old services available while switching the owner to the new URL.
2. Verify the new app and phone PWA with an authenticated user session.
3. Observe successful runtime calls, provider provenance, database persistence after restart and workspace sync.
4. Retire the old services through Render Dashboard controls, never by deleting their source repositories.
5. Retain old deployment IDs, source SHAs, data exports and rollback steps for the agreed observation period.
