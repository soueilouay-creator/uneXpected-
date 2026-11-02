Plan: docs/plans/2026-11-02-unexpected-v8-single-command-center.md

Task 1: completed
- Desktop command-center shell and same-origin read APIs implemented.
- Authenticated reads, static-asset traversal protection, and explicit /mobile/ 404 verified.

Task 2: complete_for_mock_route; live_model_credentials_pending
- Native Anthropic, OpenAI/OpenRouter Chat Completions, and OpenOx Responses API adapters implemented. OpenOx route is registered only when OPENOX_API_KEY is present; it defaults to gpt-6-astra and remains unverified until the bounded provider test succeeds.
- Per-task route selection remains immutable across concurrent requests and full lifecycle stages.
- Bounded live provider-test endpoint and provider provenance audit events implemented.
- Provider route, concurrent routing, coordinator, lifecycle and HTTP tests pass.
- Render v8 is configured with OPENOX_BASE_URL=https://api.openoxai.com/v1, OPENOX_MODEL=gpt-6-astra and UNEXPECTED_DEFAULT_PROVIDER=openox. Live /health reports provider=openox and provider_configured=true; no credential value was read or logged. The authenticated OpenOx Test connection has not yet been run, so the route remains unverified and full lifecycle is still gated.

Task 3: adapter_and_manual_branch_recovery_verified; scheduled_backup_pending
- PostgreSQL StateStore adapter, PostgreSQL idempotency mixin, and PostgreSQL one-use approval ledger implemented.
- Fresh-database migrations 001 and 002 and Python psycopg adapter are exercised in ephemeral PostgreSQL 16 CI.
- Neon branch v8-migration-test (br-young-resonance-b9unjqzy) has migration 002 applied and verified; duplicate idempotency and approval consumption are rejected.
- Manual Neon branch-recovery test passed with isolated test rows only.
- New Render v8 runtime returned /health HTTP 200 with storage=ready, verifying a live database query.
- Original Neon main branch remains at schema version 1; no production schema was changed.
- Remaining: establish scheduled/manual backup policy and restore rehearsal on actual runtime data.

Task 4: desktop_command_center_live; authenticated_browser_session_pending
- Task submission, task detail, task/event history, provider status/selection/testing, capabilities, governance visibility and improvement proposal controls are connected to the same Coordinator/API.
- GitHub Actions full HTTP integration verifies health, authentication, all 38 agents, task invocation, task detail, provider provenance, idempotent replay, desktop UI and /mobile/ 404.
- Public live checks on the v8 service:
  * /health HTTP 200, version=8.0.0-preview, storage=ready, authentication_configured=true, privileged_actions=fail-closed.
  * / HTTP 200, title uneXpected — Command Center.
  * /assets/app.js HTTP 200.
  * /assets/styles.css HTTP 200.
  * /mobile/ HTTP 404.
- Authenticated hosted status and task invocation have not been tested remotely from this session; local-container authenticated tests pass. The token is stored only in Render private settings and must be copied from there into the command center by the owner.
- Promotion, rollback and privileged approval actions are not exposed.

Task 5: single_service_live; final_manual_settings_pending
- Single-process Python Dockerfile copies all manifest-pinned skill sources, including self_improvement/.
- GitHub Actions run 41445620877 passed **186 tests, 1 skipped**, real PostgreSQL integration, Docker build, actual container smoke test (health, UI, auth, 38 agents, mock task invocation) and CLI smoke tests.
- New Render service: unexpected-v8-command-center (srv-dbk8217b9u1s73ftauig), free Frankfurt, branch feat/unified-v8-foundation, auto-deploy disabled.
- Latest v8 deployment dep-dbk86nou01pc739b3tb0 is live at commit c145e2d9b3896d5ad7ee9b405619ac78c4392089.
- DATABASE_URL for isolated Neon v8-migration-test branch and a 96-character access token are stored directly in Render private environment settings.
- The original Render service healthCheckPath remains blank. Render connector does not expose a setter; owner must set /health in the service Dashboard -> Settings -> Health Check Path.
- Real provider credentials are not configured; deterministic mock is the active route.
- Existing AI Studio, v7.3.1 runtime test and old v8 unified test services are untouched pending cutover acceptance.

Execution boundary:
- Work remains on feat/unified-v8-foundation; PR #11 remains draft and is not merged.
- No production Render settings, old live services, provider secrets or parent Neon schema have been changed.
- New v8 Render service uses isolated Neon test branch, not the parent branch.
- Phone/PWA is excluded from v8. Legacy source is retained only for rollback.
- Consequential actions remain disabled until durable approval, replay, backup and restore gates pass and the owner separately approves activation.
