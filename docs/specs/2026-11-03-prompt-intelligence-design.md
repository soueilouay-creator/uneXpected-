# Prompt Intelligence — Permanent uneXpected Capability

**Status:** Approved architecture; implemented in draft PR #19; current-head verification is tracked in GitHub Actions  
**Date:** 2026-11-03  
**Integration base:** `feat/v8.1-durable-traces` at upstream commit `da89926b965dc62fa72800bf909c844692a1b4ef`; one runtime and one Command Center

## Goal

Turn the existing AI Money Move title index into a permanent, source-agnostic Prompt Intelligence subsystem. Every future prompt source must enter through one durable catalogue and the same provenance, rights, specialist-mapping, safety-evaluation, permission and activation gates.

## Architecture

Prompt Intelligence is a domain service inside the existing Python runtime. It is not another agent, coordinator, service, or independent database. It uses the existing Coordinator, the 38-role AgentRegistry, the shared SQLite/PostgreSQL StateStore, PermissionPolicy, one-use host approvals, audit events and the existing command center.

The prompt-source registry is deliberately separate from Resource Intelligence: a research resource is a candidate reference; a prompt is a versioned task template that may be selected for execution. Both retain provenance and never install or authorize capabilities.

### Main components

1. **Prompt Source Registry** — identifies each publisher/source and records canonical URL, publisher, source type, terms/licence URLs, rights status, attribution, retention policy and source status.
2. **Prompt Version Catalogue** — stores stable prompt IDs, source IDs, external IDs, category, title, source URL, immutable versions, content hashes and review state. A prompt version is not editable in place.
3. **Ingestion Contract** — a provider-neutral import batch used by manual JSON import today and any future reviewed connector. Connectors may retrieve candidate metadata/content, but every result enters the same staging path. No crawler or connector network session is started by registration.
4. **Rights and Retention Gate** — unknown or restricted rights permit metadata-only records; original prompt bodies are retained only for a user-supplied source, an evidenced open licence or explicit permission. A missing rights record never becomes permission by inference.
5. **Specialist Mapper** — maps each prompt version to one existing canonical role. Suggested mappings are hints; an existing AgentRegistry role is required and the mapping is recorded in the reviewed version.
6. **Safety and Quality Evaluator** — computes a deterministic, versioned report over the prompt title/body, checking source integrity and prompt-injection/policy-override patterns. It records hashes and findings, not claims of human approval.
7. **Activation Gate** — promotes only a reviewed, rights-cleared, mapped, evaluated version. Activation is a modify_policy action and must pass the existing host-verified, one-use, action-bound approval verifier. The approval digest binds source ID, prompt ID/version, body hash, rights evidence, mapped role and evaluation report digest.
8. **Command Center UI and API** — exposes active prompts for normal search/selection and a separate owner-facing source/review queue for staging, review and activation.

## Lifecycle

source registered → source rights reviewed → prompt batch staged → prompt version reviewed → evaluated → ready for activation → active

Non-active outcomes are rejected, suspended or archived. A new version of an already-active prompt is staged independently; the old active version remains available until the new version is approved and activated. Exact duplicate source/external-ID/content-hash imports are idempotent.

### Rights and body-retention rules

- unknown or restricted: metadata-only; no original prompt body may be stored or passed to a model.
- metadata_only: store title/category/source metadata and generate uneXpected-native instructions.
- open_license: retain source text only with a recorded licence/terms evidence URL and attribution.
- permission_granted: retain source text only with a recorded permission evidence URL and attribution.
- user_supplied: the user's submitted text may be retained as user-provided, with source attribution recorded as user-provided.
- A content_allowed record is rejected unless its source rights status is open_license, permission_granted or user_supplied and evidence/attribution requirements are met.

The existing AI Money Move directory remains unknown + metadata_only: the imported 1,178 titles and 15 category labels are retained with attribution, but its original prompt bodies are not copied.

## Permission and trust boundaries

- Imported titles, categories, source bodies, metadata, and connector output are untrusted data. They cannot modify system instructions or review state.
- A prompt can never request, add or grant runtime permissions. The imported required_permissions field is rejected. Privileged operations remain separate user requests governed by the existing Coordinator and PermissionPolicy.
- A mapped role's existing permissions remain the maximum scope for prompt-driven work. Prompt selection never broadens those scopes.
- Source registration/import only stages data. It cannot make a prompt executable.
- Prompt review records evidence and mapping but does not activate it. Activation fails closed when the GitHub approval verifier is absent, the approval is stale/untrusted/replayed, the action digest differs, or the candidate version changed after review.
- The original prompt body, when rights-cleared, is added to the task as untrusted user data; it is never interpolated into system instructions. A fixed runtime wrapper says to ignore attempts in source text to override policies, disclose secrets, call tools or bypass approvals.
- No background scraping, automatic upstream synchronization, MCP server installation, external message sending, publishing, spending, deployment or account changes are introduced.

## Durable storage

SQLite and PostgreSQL use the same logical records:
- prompt_sources: source identity, rights/retention evidence and status.
- prompts: stable prompt identity, source, active/candidate version pointers and lifecycle status.
- prompt_versions: immutable version payload, optional licensed body, SHA-256, review/evaluation evidence, version status and timestamp.

The PostgreSQL schema is advanced through the next additive migration. SQLite creates the equivalent tables in the existing StateStore initializer. Existing task, event, idempotency, capability and approval tables remain unchanged.

## API contract

Existing authenticated APIs remain:
- GET /v1/prompts?q=...&category=...&limit=...&offset=... — active records only; remains backward-compatible with the existing Prompt Library UI.
- GET /v1/prompts/{prompt_id} — active prompt details and uneXpected-native starter instructions.
- POST /v1/invoke and POST /v1/lifecycle — optional prompt_id, only for an active version and the exact mapped role.

New authenticated owner workflows:
- GET /v1/prompt-intelligence/sources
- POST /v1/prompt-intelligence/sources — register source metadata; status is staged.
- POST /v1/prompt-intelligence/sources/{source_id}/review — record rights/retention decision and evidence.
- POST /v1/prompt-intelligence/import — stage a bounded batch (maximum 25 records per request); no activation.
- GET /v1/prompt-intelligence/review-queue — staged and candidate versions.
- POST /v1/prompt-intelligence/prompts/{prompt_id}/review — review rights evidence, mapped role and safety report.
- POST /v1/prompt-intelligence/prompts/{prompt_id}/activate — action-bound host approval required.

All routes remain behind the existing bearer-token boundary. The API never accepts caller-supplied reserved prompt metadata on /v1/invoke.

## Acceptance criteria

1. The AI Money Move seed is persistent and idempotent: exactly 1,178 active metadata-only entries, 15 categories, 13 existing role mappings.
2. A new source can be registered and a metadata-only prompt batch staged without storing original text or activating records.
3. Unknown/restricted rights with a body are rejected; licensed/user-supplied content requires evidence and attribution.
4. Invalid/unknown role mappings, non-empty permission requests, prompt-injection findings, invalid hashes, duplicate IDs and stale candidate versions fail closed.
5. Version updates never replace the current active version until the candidate is reviewed, evaluated and approved.
6. Activation uses the existing one-use modify_policy host approval and a canonical digest over exact version/evidence/mapping/evaluation data.
7. Search/detail and task invocation expose active versions only; prompt selection is persisted with source/version/hash provenance.
8. Both SQLite and PostgreSQL storage pass persistence, uniqueness, rollback and migration tests.
9. UI can register sources, stage JSON batches, inspect the review queue and select active prompts.
10. Full regression/security tests, source-integrity manifest, Docker build, actual container API/UI/activation-gate smoke and CLI tests pass.
11. The feature is a draft PR stacked on the v8.1 runtime branch until the foundation and dependent v8.1 PRs are independently reviewed and merged.

## Operational scope

This implementation establishes the permanent local/runtime capability and its tested APIs. Production deployment, selecting a Render workspace, live provider/connector authorization, enabling privileged execution and retiring old services remain separate release operations with their own verification and approval.
