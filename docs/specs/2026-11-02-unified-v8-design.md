# uneXpected v8 Unified System — Design

**Date:** 2026-11-02  
**Status:** Approved for implementation by the owner in this conversation  
**Baseline:** `main` at `59deef5e49208c01d03ccfc6d2e162db54309235`

## Goal

Bring the governed uneXpected runtime, provider gateway, web interface and phone workspace under one canonical application and command surface, while preserving existing source, role definitions, local user data and rollback paths.

## Decisions

1. The canonical repository is `soueilouay-creator/uneXpected-`, using its current `main` branch as the source baseline. The v7.3.1 test deployment branch is four commits behind and must not be the migration base.
2. The product has one user-facing application, one canonical repository, one public API boundary and one system-wide task/data model.
3. Keep the current Node.js gateway/interface and Python governed runtime as separately testable internal modules in the same deployable application. The Node process owns the public listener; the Python runtime binds only to loopback and is supervised by the same container entrypoint. This avoids a public service-to-service bearer-token hop. The two components are not independent public applications.
4. Use a Neon Free PostgreSQL project as the initial shared durable store, conditional on the provider confirming $0 pricing and quotas at creation. Do not create any paid resource or enable a paid plan. A quota pause must fail closed and must not switch writes back to ephemeral disk.
5. Keep the 38 canonical roles, instructions, routing, skills, current workflow lifecycle, benchmark/evaluation and improvement governor. No agent count expansion during consolidation.
6. Preserve the web UI, phone PWA, provider selection, OpenAI/Anthropic/OpenRouter behavior, TAAFT read-only discovery and existing mobile offline mode. Provider keys remain server-side.
7. Maintain the existing owner-only bearer access boundary initially. A multi-user identity/account system is out of scope until separately designed.
8. Keep existing deployments live as rollback sources throughout migration. No old service is deleted, suspended, renamed, or reconfigured before the new service passes the cutover checklist.
9. Keep consequential actions disabled. No publication, payment, account mutation, repository write, deployment or other privileged external action is allowed until durable transactional approval, independent approver identity, action-digest binding, expiry and one-use replay prevention are verified.
10. Treat ChatGPT connector access as separate from server integrations. GitHub/Render/Metricool or other connector adapters may be registered in the unified system, but they are not considered authorized merely because ChatGPT has a connected app. Each adapter requires its own server-side credential, allowlist, least-privilege scope and tests.

## System boundary

- **Public application:** Node.js HTTP gateway, browser UI, mobile PWA and owner authentication.
- **Internal runtime:** Python coordinator and seven-stage lifecycle (`Request → Plan → Execute → Verify → Improve → Deliver → Learn`) on loopback only.
- **Provider layer:** Node gateway retains OpenAI, Anthropic and optional OpenRouter keys. The Python coordinator calls the internal gateway over loopback with a runtime-generated, process-local secret.
- **Shared database:** PostgreSQL for task/event state, idempotency, per-agent memory, shared knowledge, outcomes, improvement proposals/baselines/version history, approval replay ledger and device/workspace snapshots.
- **Local-first workspace:** existing IndexedDB records remain available offline. Server sync is additive and versioned; import never silently replaces local records. The user can export a full JSON backup at any time.
- **Connectors:** explicit adapters behind the central permission policy; no generic unrestricted tool execution.

## Data preservation and migration

- Preserve the complete current `main` source tree, including catalog/crosswalks/manifests, agents, skill profiles, governance, tests, docs and the latest lifecycle implementation.
- Copy the current AI Studio distribution by its reviewed repository revision, including server/provider/TAAFT code, mobile PWA assets, archive/chunk assets and Node tests. Record source commit and file hashes in a migration manifest.
- Before any existing SQLite state is moved, inventory its tables and row counts using a verified export or a host-side backup. The Render Free filesystem is ephemeral, so any SQLite data not captured before restart/redeploy may already be unavailable. Do not claim the database is empty or migrated without evidence.
- Keep each phone/device IndexedDB workspace local until it exports a backup. Import into the unified system additively using stable record IDs and conflict records. The first server sync is a copy, not a destructive move.
- PostgreSQL schema migrations are versioned and transactional. Database failure blocks new writes and never silently falls back to temporary local SQLite.
- Store database connection strings and provider secrets only in the host secret manager; never commit or print values.

## Deployment and health

- Build one Docker image from the canonical repository. The image contains Node.js and Python runtime dependencies pinned in source.
- Start the Python runtime bound to `127.0.0.1` on a private port, then start the Node public server after the runtime passes readiness. If either component exits unexpectedly, the supervisor terminates the application so the platform can restart it.
- The public `/health` endpoint checks both public application and internal runtime readiness, and reports configuration presence only (never secret values).
- Render Free web services sleep after 15 minutes idle and have ephemeral filesystems; Neon Free can suspend compute at monthly quota limits. This is a $0 testing/hobby deployment, not a 24/7 production availability guarantee.
- A combined Node+Python container must pass memory/load testing on the available Render Free instance before cutover. If it cannot, retain a single command-center product with separately hosted internal modules rather than claim the one-container target is stable.

## Verification gates

1. Repository and migration manifest reconcile to source commits and hashes.
2. All current Python tests and Node mobile/gateway tests pass in CI.
3. Runtime API rejects missing/invalid tokens, unknown fields and privileged scope claims; public health leaks no secret.
4. One lifecycle invocation runs through all seven stages using deterministic mock and returns verified delivery; failed verification blocks delivery.
5. OpenRouter smoke test and one live runtime invocation return explicit provider/model provenance, when a usable free provider route is configured. No paid provider call unless explicitly approved and funded.
6. PostgreSQL migration, restart persistence, transaction rollback, idempotency uniqueness and one-use replay tests pass.
7. Workspace export/import, duplicate handling and restore tests pass without deleting local records.
8. Container build, startup, both-process health and failure/restart behavior pass; memory and cold-start are measured.
9. New Render deployment passes authenticated end-to-end tests before old services are retired.

## Rollback

Keep the old Node Studio and Python test service unchanged until cutover. Retain their Git revisions, deploy IDs, environment configuration names and known endpoints in a non-secret ledger. If the new deploy fails, route back to the existing Studio; do not downgrade or overwrite the canonical runtime source. Database rollback uses a pre-migration snapshot and tested reverse/restore procedure, not ad hoc table deletion.

## External references

- Render free service constraints: https://render.com/docs/free
- Render deployment/storage behavior: https://render.com/docs/deploys
- Neon Free quotas: https://neon.com/docs/introduction/plans
