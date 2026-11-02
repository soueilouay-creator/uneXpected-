Plan: docs/plans/2026-11-02-unexpected-v8-single-command-center.md

Task 1: completed
- Desktop command-center shell and same-origin read APIs implemented.
- Authenticated API reads, static asset traversal protection, and explicit /mobile/ 404 verified.
- GitHub Actions run 41438724103 passed the full 144-test suite (1 optional test skipped).

Task 2: completed_pending_manifest
- Native Anthropic adapter, OpenAI/OpenRouter route registry, immutable per-task route selection, and bounded provider connectivity test implemented.
- Command center exposes provider selection and live test controls.
- Provider adapter, concurrent routing, coordinator and API tests passed in GitHub Actions; full run was blocked only by the source-integrity manifest after new files were added.

Task 3: in_progress
- PostgreSQL StateStore adapter, atomic idempotency claims, PostgreSQL one-use approval ledger, and additive migration 002 implemented.
- SQLite single-flight idempotency and Postgres adapter/approval-ledger contract tests pass in CI.
- Neon project schema was inspected read-only; migration 001 exists and the v8 tables are empty. Migration 002 has NOT been applied to the project.
- Next: create/verify an isolated Neon branch, apply migration 002 there, run actual Postgres integration/recovery tests, then consider preview configuration.

Task 4: pending
Task 5: pending

Execution boundary:
- Work remains on feat/unified-v8-foundation.
- No production Render settings, live services, provider secrets, or Neon database schemas have been changed.
- Neon project tiny-glade-03545028 remains untouched; current branch is still at schema version 1.
- Phone/PWA remains excluded.
- Consequential actions remain disabled until durable approval, replay, backup and restore gates pass.
- No paid resource has been created.
