Plan: docs/plans/2026-11-02-unexpected-v8-single-command-center.md

Task 1: completed
- Desktop command-center shell and same-origin read APIs implemented.
- Authenticated reads, static-asset traversal protection, and explicit /mobile/ 404 verified.

Task 2: completed
- Native Anthropic adapter and OpenAI/OpenRouter routes implemented.
- Per-task route selection remains immutable across concurrent requests and full lifecycle stages.
- Bounded live provider-test endpoint and provider provenance audit events implemented.
- Provider route, concurrent routing, coordinator, lifecycle and HTTP tests pass.
- Real provider credentials have not been migrated or tested on the preview service.

Task 3: database_adapter_and_manual_branch_recovery_verified; scheduled_backup_pending
- PostgreSQL StateStore adapter, PostgreSQL idempotency mixin, and PostgreSQL one-use approval ledger implemented.
- Fresh-database migrations 001 and 002 and the Python psycopg adapter are exercised in ephemeral PostgreSQL 16 CI.
- Neon branch v8-migration-test (br-young-resonance-b9unjqzy) has migration 002 applied and verified; duplicate idempotency and approval consumption are rejected.
- Manual Neon branch-recovery test passed using isolated test rows only.
- Original Neon main branch remains at schema version 1; no production schema was changed.
- Remaining: scheduled/manual backup policy and restore rehearsal on actual runtime data.

Task 4: command_center_api_and_ui_integration_verified; hosted_browser_pending
- Task submission, task detail, task/event history, provider status/selection/testing, capabilities, governance visibility, and improvement proposal controls are connected to the same Coordinator/API.
- HTTP integration tests verify /health, authenticated /v1/status, all 38 agents, task invocation, task detail, provider provenance events, idempotent replay, desktop UI serving and /mobile/ 404.
- Promotion, rollback and privileged approval actions are not exposed.
- Remaining: hosted browser verification and any UI/API fixes discovered there.

Task 5: container_integration_fix_pending
- Single-process Python Dockerfile and one free Render preview service definition.
- GitHub Actions has passed 185 tests previously, including real PostgreSQL and Docker build; the latest CI change adds an actual docker run smoke test.
- New Render service created: unexpected-v8-command-center (srv-dbk8217b9u1s73ftauig), free Frankfurt, branch feat/unified-v8-foundation, auto-deploy disabled.
- DATABASE_URL was added from the isolated Neon v8-migration-test branch directly into Render private environment settings. A 96-character access token was also generated and set privately in Render; neither secret was copied into chat or source.
- First image built, but startup failed because Dockerfile omitted self_improvement/ even though skill_manifest.json pins self_improvement/SKILL.md. The integrity check correctly failed closed. Fix committed: Dockerfile now copies self_improvement/; CI now boots the actual image and tests health, UI, authentication, all 38 agents and a real mock invocation.
- Next: wait for clean CI, manually redeploy service, verify live health/status/task persistence, and configure Render healthCheckPath=/health (the Render service-create connector does not expose this setting).
- Real model-provider credentials have not been configured; preview defaults to deterministic mock.
- Existing AI Studio, v7.3.1 runtime test and old v8 unified test services are untouched.

Execution boundary:
- Work remains on feat/unified-v8-foundation; PR #11 remains draft and is not merged.
- No production Render settings, old live services, provider secrets, or parent Neon schema has been changed.
- New v8 Render service uses the isolated Neon test branch, not the parent production branch.
- Phone/PWA is excluded from v8. Legacy source is retained only for rollback.
- Consequential actions remain disabled until durable approval, replay, backup and restore gates pass and the owner separately approves activation.
