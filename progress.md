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

Task 3: in_progress
- PostgreSQL StateStore adapter, PostgreSQL idempotency mixin, and PostgreSQL one-use approval ledger implemented.
- SQLite and mocked-Postgres contract tests cover concurrent claim/consume, replay, digest mismatch, failure and schema gating.
- Neon project tiny-glade-03545028 was inspected read-only on its parent branch (schema v1; runtime tables empty except schema_migrations).
- Isolated Neon branch v8-migration-test (br-young-resonance-b9unjqzy) created. Migration 002 was applied and verified there.
- SQL-level tests confirmed one idempotency claim winner, one approval consumption winner, and duplicate/altered-digest attempts do not overwrite the original record. Test rows were cleaned.
- Parent branch remains at schema v1. No production schema was changed.
- Remaining: exercise the Python psycopg adapter from a hosted preview, verify backup/export and restore, and inspect real runtime persistence.

Task 4: in_progress
- Task submission, task detail, task/event history, provider status/selection/testing, capabilities, governance visibility, and improvement proposal controls are connected to the same Coordinator/API.
- Promotion, rollback and privileged approval actions are not exposed.
- Remaining: live browser preview verification and any UI/API fixes discovered there.

Task 5: in_progress
- Single-process Python Dockerfile and one free Render preview Blueprint added.
- GitHub Actions run 41441245951 passed: 179 tests, 1 optional skip; Docker image build and CLI smoke tests passed.
- Draft PR #11 is open from feat/unified-v8-foundation to main.
- A hosted preview was not created. The cross-connector transfer of the Neon connection string/API token into Render was blocked by safety checks; no secret was exposed and no Render service was changed.
- Existing Render services (AI Studio, v7.3.1 runtime test, and earlier v8 unified test) remain untouched.
- Remaining: configure the Blueprint directly in Render using its generated API token and the Neon test-branch connection string, deploy, authenticate, test the Python Postgres adapter and rehearse rollback.

Execution boundary:
- Work remains on feat/unified-v8-foundation; PR #11 remains a draft and is not merged.
- No production Render settings, live services, provider secrets, or parent Neon database schemas have been changed.
- Neon migration test branch is isolated; no paid resource has been created.
- Phone/PWA is excluded from v8. Its legacy source remains untouched for rollback and is not packaged in the new app.
- Consequential actions remain disabled until durable approval, replay, backup and restore gates pass and the owner separately approves activation.
