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
- Fresh-database migration 001 and additive migration 002 applied to a real ephemeral PostgreSQL 16 service in CI.
- GitHub Actions run 41442316659 passed **184 tests, 1 optional skip**; actual psycopg integration tests covered tasks, events, memory, knowledge, outcomes, baselines, versions, proposals, capabilities, atomic idempotency claims/replay and one-use approvals.
- Isolated Neon branch v8-migration-test (br-young-resonance-b9unjqzy) has migration 002 applied and verified; duplicate idempotency and approval consumption are rejected.
- Manual Neon branch-recovery test passed: v8-recovery-check (br-flat-waterfall-b9n6lhib) preserved test task, idempotency and consumed-approval records after those rows were deleted from its parent test branch.
- The recovery-check branch contains only test rows and was left in place after branch deletion was blocked by safety checks. No production data is in it.
- Original Neon main branch remains at schema version 1; no production schema was changed.
- Remaining: hosted Render connection, scheduled/manual export policy, backup retention and restore rehearsal on real runtime data.

Task 4: in_progress
- Task submission, task detail, task/event history, provider status/selection/testing, capabilities, governance visibility, and improvement proposal controls are connected to the same Coordinator/API.
- Promotion, rollback and privileged approval actions are not exposed.
- Remaining: live browser preview verification and any UI/API fixes discovered there.

Task 5: in_progress
- Single-process Python Dockerfile and one free Render preview Blueprint added.
- GitHub Actions run 41442316659 passed: 184 tests, 1 optional skip; Docker image build and CLI smoke tests passed.
- Draft PR #11 is open from feat/unified-v8-foundation to main.
- A hosted preview was not created. The cross-connector transfer of the Neon connection string/API token into Render was blocked by safety checks; no secret was exposed and no Render service was changed.
- Existing Render services (AI Studio, v7.3.1 runtime test, and earlier v8 unified test) remain untouched.
- Remaining: configure the Blueprint or repurpose the existing v8 test service directly in Render, deploy, authenticate, test the hosted adapter and rehearse rollback.

Execution boundary:
- Work remains on feat/unified-v8-foundation; PR #11 remains a draft and is not merged.
- No production Render settings, live services, provider secrets, or parent Neon database schemas have been changed.
- Neon migration/recovery test branches are isolated; no paid resource has been created.
- Phone/PWA is excluded from v8. Its legacy source remains untouched for rollback and is not packaged in the new app.
- Consequential actions remain disabled until durable approval, replay, backup and restore gates pass and the owner separately approves activation.
