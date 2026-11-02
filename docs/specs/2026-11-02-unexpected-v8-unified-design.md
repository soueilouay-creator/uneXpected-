# uneXpected v8 Unified Application — Design Specification

**Status:** Proposed for owner review  
**Date:** 2026-11-02  
**Canonical source:** `soueilouay-creator/uneXpected-`, branch `main`  
**Implementation branch:** `feat/unified-v8-foundation`

## 1. Goal

Consolidate the governed Python runtime and the Node.js AI Studio/mobile workspace into one maintainable uneXpected application with one public entry point, one routing and policy boundary, one durable data layer, and a shared command center, while preserving existing workflows, specialist definitions, project data, user workspace records, provider adapters, and integrations.

This is a migration, not a clean-slate rewrite. Existing deployments remain available until the unified release is proven and cutover is explicitly completed.

## 2. Repository findings that shape the design

- The Python repository's `main` branch is the canonical governed runtime baseline. It contains the 38-role registry, skill and capability manifests, provider abstraction, coordinator, the Request → Plan → Execute → Verify → Improve → Deliver → Learn lifecycle, tests, and current API endpoints.
- The Render Python test service currently deploys `integration/v7.3.1-governed-runtime`, which is four commits behind `main`. The current `main` has newer `/v1/lifecycle` support and additional bounded execution controls. The integration branch must not be used as the migration baseline.
- The Node.js AI Studio repository contains the web interface, mobile PWA, provider orchestration, access-token authentication, and read-only TAAFT catalog integration. Its Render service is separate from the Python runtime service.
- The mobile PWA stores projects, conversations, memories, and improvement notes in device-local IndexedDB. It supports JSON backup export/import. Import currently replaces local records, so migration must add a non-destructive merge path and retain the original backup.
- The Python runtime uses SQLite for tasks, events, agent memory, shared knowledge, idempotency results, outcomes, proposals, versions, and capabilities. The current Render Free service has no verified durable disk; its live SQLite contents have not yet been recovered or inspected.
- No existing Neon project matching uneXpected was found. No database will be created until the storage migration design and free-tier constraints are confirmed.

## 3. Recommended architecture

### 3.1 One public application, modular internals

Use the Python repository as the canonical repository and merge the Node.js AI Studio and mobile PWA source into it. Deliver one deployable Docker application and one public Render web service.

Recommended initial process arrangement:
- Node.js remains the public web/API server and serves the existing web and mobile PWA assets.
- The governed Python runtime runs as a private loopback-only child process in the same container.
- Node.js calls Python over localhost only; the Python API is not independently internet-exposed.
- A single container supervisor starts both processes, checks both processes, forwards termination signals, and exits unhealthy if either required process fails.
- The public `/health` endpoint reports interface and runtime readiness separately and returns unhealthy when the required runtime is unavailable.
- Keep provider adapters and specialist execution behind the governed coordinator. The UI must not bypass role routing, permissions, audit, or verification.

This keeps the existing languages and useful code while removing the separate public service and bearer-token network bridge. It is a single deployable system, not a monolithic code file.

### 3.2 Unified data layer

Use PostgreSQL as the shared durable source of truth for server-side task state, audit/events, idempotency/replay records, agent memory, shared knowledge, outcomes, proposals, version history, capabilities, and approval consumption.

Recommended initial provider: Neon Free, subject to a pre-provisioning review of current quotas, billing safeguards, and backup/restore behavior. Do not enable a paid compute tier or paid storage. If the $0 constraint cannot be maintained, keep privileged execution disabled and present a blocker rather than silently selecting a paid service.

Keep schema migrations versioned and additive. Preserve SQLite import/export tooling until PostgreSQL records have been reconciled and a restore test has passed. Do not delete the old SQLite files or old service during migration.

### 3.3 Workspace records

Add authenticated workspace APIs for projects, conversations, user memories, settings, and improvement notes. Add a versioned IndexedDB backup importer that:
- validates the backup envelope and schema version;
- previews counts and conflicts before writing;
- merges by stable record ID by default;
- never silently overwrites an existing record;
- records import provenance and timestamps;
- allows an explicit, separately confirmed replace operation only when the user chooses it;
- retains the original uploaded backup unchanged.

Existing device-local records remain on the device until the server import is verified. No access token or provider secret is included in exported workspace backups.

### 3.4 Unified security boundary

- Keep one public access-token boundary at the Node.js gateway.
- Keep Python bound to loopback and reject non-loopback binding in production configuration.
- Remove the inter-service runtime token only after internal transport is verified and external access to Python is impossible.
- Store provider and database secrets only in the hosting secret manager; never write values into the repository, logs, client bundle, or backup.
- Preserve least privilege and explicit integration allowlists.
- Consequential execution remains disabled until approval records are durable, transactional, action-digest-bound, expiring, authenticated, and atomically consumed once. Replay tests and restore tests must pass before activation.
- The GitHub PR approval verifier's local SQLite one-use ledger is not sufficient for production until its consumption operation is backed by durable transactional storage.
- Keep the existing fail-closed behavior for privileged operations.

### 3.5 Providers and integrations

Retain existing OpenAI, Anthropic, OpenRouter and read-only TAAFT discovery behavior. Provider selection must be performed through a single adapter registry and report configured, reachable, and verified states separately. Do not claim provider connectivity from the presence of a secret alone.

Integrations such as GitHub, Render, Metricool, creative-media services, and future connectors must use a shared capability registry with provenance, permission scopes, health checks, and per-action approval policy. A catalog entry or prompt is not evidence that a connector is installed or authorized.

## 4. Preservation and migration requirements

1. Preserve all 38 canonical roles and their IDs, descriptions, permissions, routing metadata, and mapped skills. Add automated count and manifest checksum checks.
2. Preserve the existing seven-stage workflow and current tests. No stage may be skipped by the UI path.
3. Preserve provider adapters and the current read-only TAAFT allowlist.
4. Preserve all Node.js web and mobile assets, existing UI routes, and voice/PWA features.
5. Preserve user-local IndexedDB records through a non-destructive export/merge process.
6. Recover runtime SQLite records from the old service if accessible. If they cannot be recovered, explicitly record that as a data-loss limitation; do not claim the migration is complete.
7. Preserve all source repositories and old deployments until cutover verification and an agreed rollback window have passed.
8. Never copy credentials or environment-variable values into Git, logs, migration artifacts, or this design document.

## 5. Failure behavior and rollback

- If Python child process startup fails, public health is unhealthy and workflow execution is rejected.
- If PostgreSQL is unavailable, reject writes that require durable state; do not silently fall back to ephemeral SQLite for approvals, idempotency, or audit.
- If provider calls fail, return explicit provider-specific failures and keep deterministic mock mode clearly labeled as mock.
- If a migration batch fails, leave the source unchanged, roll back the target transaction, record the failed batch, and allow a bounded retry after inspection.
- Keep the old Render services and deployment revisions live until the new service passes smoke tests, authenticated invocation, lifecycle verification, backup/restore, and data reconciliation.
- Cutover and service retirement are separate operations. Do not delete repositories, databases, old SQLite artifacts, or old Render services as part of initial deployment.

## 6. Acceptance criteria

- One public Render web service serves the web UI, mobile PWA, API, and governed runtime.
- Python runtime is not publicly reachable and is controlled by the Node.js gateway.
- `/health` proves both UI and runtime readiness; authenticated status and invocation are verified.
- The full seven-stage workflow completes one deterministic test task and one approved low-risk real provider task with independent verification.
- The registry contains exactly 38 canonical roles and manifest hashes match.
- All existing Python regression tests pass; new integration, auth, process-supervision, storage, and migration tests pass.
- PostgreSQL schema migrations, atomic idempotency, one-use approval consumption, backup, and restore tests pass.
- Workspace backup import merges without data loss and can be reconciled by stable IDs.
- No privileged action is enabled until the durable approval and replay tests pass.
- The $0 hosting/storage constraint is maintained or work stops before any paid resource is provisioned.
- Old services are not retired until the user-facing unified service passes all acceptance criteria and rollback has been rehearsed.

## 7. Explicit non-goals for the first migration

- No full rewrite of specialist logic.
- No increase in the number of canonical roles beyond 38.
- No automatic enablement of third-party write-capable integrations.
- No autonomous publishing, spending, payments, account changes, or production deployments.
- No deletion of the original repositories or old services during migration.
- No promise that all external apps can be controlled until each connector is independently authorized and tested.

## 8. Migration stages

1. Preserve and inventory all source revisions, local backup paths, runtime data accessibility, service settings, and secret names (never values).
2. Add a non-destructive design and implementation branch; merge the AI Studio interface and PWA assets into the canonical Python repository.
3. Add process supervision, private loopback runtime invocation, unified health, and end-to-end API tests.
4. Add PostgreSQL schema and migration adapters, then test SQLite-to-PostgreSQL and workspace JSON imports.
5. Add shared provider/capability routing, status reporting, and safe integration permission boundaries.
6. Deploy a separate unified preview service; run tests and data reconciliation without changing current production traffic.
7. Cut over only after acceptance criteria pass; keep old services available through the rollback window.
8. Retire old services only after explicit final confirmation and verified rollback readiness.
