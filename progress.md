Plan: docs/plans/2026-11-02-unexpected-v8-single-command-center.md

Task 1: completed
- Desktop command-center shell and same-origin read APIs implemented.
- Authenticated reads, static-asset traversal protection, and explicit /mobile/ 404 verified.
- GitHub Actions run 41438724103 passed the initial full 144-test suite (1 optional test skipped).

Task 2: completed_pending_final_ci
- Native Anthropic adapter and OpenAI/OpenRouter routes implemented.
- Per-task route selection is immutable across concurrent requests and full lifecycle stages.
- Bounded live provider-test endpoint and provider provenance audit events implemented.
- Provider route, concurrent routing, HTTP, and lifecycle tests pass in CI.
- Real provider credentials have not been migrated or tested on the preview service.

Task 3: in_progress
- PostgreSQL StateStore adapter, PostgreSQL idempotency mixin, and PostgreSQL one-use approval ledger implemented.
- SQLite and mocked-Postgres contract tests cover concurrent claim/consume, replay, digest mismatch, failure and schema gating.
- Neon project tiny-glade-03545028 was inspected read-only on its parent branch (schema v1, runtime tables empty except schema_migrations).
- Isolated Neon branch v8-migration-test (br-young-resonance-b9unjqzy) created. Migration 002 was applied and verified there.
- SQL-level tests confirmed one idempotency claim winner, one approval consumption winner, and duplicate/altered-digest attempts do not overwrite the original record. Test rows were cleaned.
- Parent branch remains at schema v1. No production schema was changed.
- Remaining: test the Python psycopg adapter against the Neon test branch, verify backup/export and restore, and inspect actual runtime persistence.

Task 4: in_progress
- Task submission, task detail, task/event history, provider status/selection/testing, capabilities, governance visibility, and improvement proposal controls are connected to the same Coordinator/API.
- Promotion, rollback and privileged approval actions are not exposed.
- Remaining: browser-level preview verification and any UI/API fixes discovered there.

Task 5: in_progress
- Single-process Python Dockerfile and one free Render preview Blueprint added.
- CI now installs psycopg and builds the container after the full regression suite.
- Existing AI Studio and Python Render services remain untouched.
- Remaining: clean CI pass, preview deployment, authenticated runtime verification, Postgres adapter test, and rollback rehearsal.

Execution boundary:
- Work remains on feat/unified-v8-foundation.
- No production Render settings, live services, provider secrets, or parent Neon database schemas have been changed.
- Neon test branch is isolated; no paid resource has been created.
- Phone/PWA remains excluded.
- Consequential actions remain disabled until durable approval, replay, backup and restore gates pass and the owner separately approves activation.
