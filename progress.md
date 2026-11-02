Plan: docs/plans/2026-11-02-unexpected-v8-single-command-center.md

Task 1: completed
- Desktop command-center shell and same-origin read APIs implemented.
- Authenticated reads, static-asset traversal protection, and explicit /mobile/ 404 verified.

Task 2: completed
- Native Anthropic adapter and OpenAI/OpenRouter routes implemented.
- Per-task route selection remains immutable across concurrent requests and full lifecycle stages.
- Bounded live provider-test endpoint and provider provenance audit events implemented.
- Provider route, concurrent routing, coordinator, lifecycle and HTTP tests pass.
- Real provider credentials have not been migrated or tested; deployment defaults to deterministic mock.

Task 3: database_adapter_and_manual_branch_recovery_verified; scheduled_backup_pending
- PostgreSQL StateStore adapter, PostgreSQL idempotency mixin, and PostgreSQL one-use approval ledger implemented.
- Fresh-database migrations 001 and 002 and Python psycopg adapter are exercised in ephemeral PostgreSQL 16 CI.
- Neon branch v8-migration-test (br-young-resonance-b9unjqzy) has migration 002 applied and verified; duplicate idempotency and approval consumption are rejected.
- Manual Neon branch-recovery test passed using isolated test rows only.
- Original Neon main branch remains at schema version 1; no production schema was changed.
- Hosted /health request returned HTTP 200 with storage=ready, authentication_configured=true and privileged_actions=fail-closed, confirming a live Neon query from the new Render runtime.
- Remaining: scheduled/manual backup policy and restore rehearsal on actual runtime data.

Task 4: command_center_api_and_ui_integration_verified; hosted_auth_flow_pending
- Task submission, task detail, task/event history, provider status/selection/testing, capabilities, governance visibility and improvement proposal controls are connected to the same Coordinator/API.
- GitHub Actions full HTTP integration verifies health, auth, all 38 agents, task invocation, task detail, provider provenance, idempotent replay, desktop UI and /mobile/ 404.
- Hosted command-center root returned HTTP 200 and served the expected uneXpected UI.
- Hosted authenticated status/task invocation has not yet been sent; the API token is stored privately in Render and not exposed in chat.
- Promotion, rollback and privileged approval actions are not exposed.

Task 5: hosted_service_live; final_settings_pending
- Single-process Python Dockerfile copies all manifest-pinned skill sources, including self_improvement/.
- GitHub Actions run 41444932428 passed **186 tests, 1 skipped**, real PostgreSQL integration, Docker build, actual container smoke test (health, UI, auth, 38 agents, mock task invocation) and CLI smoke tests.
- New Render service: unexpected-v8-command-center (srv-dbk8217b9u1s73ftauig), free Frankfurt, branch feat/unified-v8-foundation, auto-deploy disabled.
- DATABASE_URL for the isolated Neon v8-migration-test branch and a 96-character access token are configured directly in Render private environment settings.
- First deploy failed because Dockerfile omitted self_improvement/. Integrity check correctly stopped startup. Dockerfile fix and actual-container CI test added.
- Latest Render deployment dep-dbk84749v7es73c082v0 is live at commit 9a6d871f608d75383cc736d68716f39ec583b328. Runtime /health and root both returned HTTP 200.
- The v8 release metadata has now been aligned to 8.0.0-preview in source; a new CI run and redeploy are pending.
- Render service healthCheckPath is currently blank. The Render connector cannot modify this setting; set /health in the service's dashboard settings.
- Real model-provider credentials are not configured; deterministic mock is the active route.
- Existing AI Studio, v7.3.1 runtime test and old v8 unified test services are untouched pending final cutover acceptance.

Execution boundary:
- Work remains on feat/unified-v8-foundation; PR #11 remains draft and is not merged.
- No production Render settings, old live services, provider secrets or parent Neon schema have been changed.
- New v8 Render service uses the isolated Neon test branch, not the parent branch.
- Phone/PWA is excluded from v8. Legacy source is retained only for rollback.
- Consequential actions remain disabled until durable approval, replay, backup and restore gates pass and the owner separately approves activation.
