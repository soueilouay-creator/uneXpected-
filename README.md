# uneXpected v8 — Single Command Center

uneXpected v8 is one governed Python application with one desktop web command center, one coordinator, one canonical 38-role registry, one provider router, and one authoritative state layer.

**The command center is the system.** It does not forward work to a separate AI Studio gateway or a second Python service.

## What is included

- One Python HTTP application and one public API boundary.
- A desktop-first command center for system health, agents, tasks, lifecycle history, providers, capabilities, approvals, audit, and improvement proposals.
- The canonical 38 specialist roles and a hash-pinned Skill bundle registry with backward-compatible v1/v2 manifests.
- The governed coordinator and seven-stage workflow: Request → Plan → Execute → Verify → Improve → Deliver → Learn.
- Resource Intelligence: permanent Awesome research index with provenance, independent license/security status and discovery-only adoption states.
- Prompt Intelligence: source-agnostic prompt registry with provenance, rights-aware ingestion, immutable versions, canonical role mapping, deterministic safety evaluation, a Command Center review workspace and action-bound approval-gated activation.
- AI Quality Evaluation: bounded deterministic output checks for instruction following, prompt injection, grounding, safety, structured output and regressions.
- Native server-side provider adapters for OpenAI, Anthropic, and OpenRouter, plus explicit deterministic mock mode.
- SQLite for local development and PostgreSQL for hosted shared state.
- Single-flight idempotency claims, replay detection, and a PostgreSQL one-use approval ledger.
- Additive database migrations and an explicit no-fallback rule for hosted PostgreSQL.
- A single Docker image and one Render web service definition.

## Explicitly excluded

- The previous phone/PWA app, mobile routes, service workers, install prompts, mobile workspace and phone-specific tests.
- The separate Node.js AI Studio server and its gateway bridge.
- Any second Python runtime service.
- Automatic publishing, spending, payments, external messaging, account changes, deployment or other consequential writes.

A future phone app, if requested, will be a separate client of the unified API. It will not contain a second coordinator or independent system state.

## Local development

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export UNEXPECTED_STORAGE_BACKEND=sqlite
export UNEXPECTED_DEFAULT_PROVIDER=mock
export UNEXPECTED_RUNTIME_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export UNEXPECTED_RUNTIME_BIND_HOST=127.0.0.1
export PORT=10000
python -m unexpected_runtime.http_api
```

Open `http://127.0.0.1:10000`. The command center asks for the API token; the browser keeps it in tab memory only. SQLite state is local development state, not durable hosted state.

Inspect the curated research catalog with `python -m unexpected_runtime.cli resources --validate`. A live quality evaluation is an explicit operator action and requires a configured, already verified non-mock route, for example `python -m unexpected_runtime.cli quality-eval --provider-route openrouter`. A mock or unverified route is rejected before evaluation tasks are created. The deterministic CI fixture suite tests evaluator contracts only; it is not live semantic model evidence.

## Prompt Intelligence

Prompt Intelligence is part of the same runtime and Command Center—not a separate service, agent registry or database. Sources follow a governed lifecycle: register provenance → review rights and retention → stage an import → map to an existing canonical role → run deterministic safety evaluation → request a one-use host approval → activate an immutable version.

The first bundled source is the AI Money Move metadata index: 1,178 titles across 15 categories mapped to 13 existing roles. Original prompt bodies are not copied because an explicit reuse licence was not established. New sources default to unknown rights and metadata-only retention. Source text is accepted only after evidence and attribution are recorded. Imported prompt content cannot add permissions, tools or roles.

The Command Center's **Prompt Intelligence** workspace manages source registration, rights review, bounded JSON imports, the review queue, role mapping, activation details and approval request preparation. Activation remains fail-closed unless the host GitHub approval verifier and trusted reviewers are configured. No crawler, automatic refresh or automatic activation is enabled.

## Provider configuration

Provider credentials must be stored in the host's secret manager, never in Git or browser storage.

- `OPENAI_API_KEY` and optional `OPENAI_MODEL`
- `ANTHROPIC_API_KEY` and optional `ANTHROPIC_MODEL`
- `OPENROUTER_API_KEY` and optional `OPENROUTER_MODEL`
- `OPENOX_API_KEY`, optional `OPENOX_BASE_URL` (default `https://api.openoxai.com/v1`) and `OPENOX_MODEL` (default `gpt-6-astra`); OpenOx uses the native `/responses` endpoint, not `/chat/completions`.
- `UNEXPECTED_DEFAULT_PROVIDER=mock|openai|anthropic|openrouter|openox`

A configured key is not a verified provider. Use the bounded **Test connection** action to verify a live route. Mock mode is never presented as a live provider.

## Hosted storage

Set `UNEXPECTED_STORAGE_BACKEND=postgres` and supply `DATABASE_URL` in the host secret manager. The app refuses to start in PostgreSQL mode if the URL or required v8 schema is unavailable; it never silently falls back to ephemeral SQLite.

Apply migrations in order from an isolated database branch before configuring the service:

1. `migrations/001_initial.sql` for a fresh database (or verify the existing schema-v1 baseline).
2. `migrations/002_idempotency_claims.sql`.
3. `migrations/003_prompt_intelligence.sql` for the governed Prompt Intelligence source, prompt and immutable-version tables.

For a fresh PostgreSQL database, apply migrations 001, 002 and 003 in order. For an existing schema-v1 database, compare it against migration 001, then apply migrations 002 and 003. Do not expose Prompt Intelligence endpoints against a database until migration 003 has been applied. The included Render Blueprint creates one free web service only; it does not create a database.

The current Neon Free plan has no scheduled backup snapshots. Verify the current limits, backup/export destination, and restore process before relying on it for durable production records.

## Verified Skill bundles

The authenticated command center exposes `GET /v1/skills` for metadata-only Skill discovery. `POST /v1/invoke` accepts an optional `skill_ids` array (up to four unique IDs) for explicit user-invoked Skills. Task records persist the selected IDs, and the idempotency/approval action digests bind the selection.

- Manifest schema v1 remains compatible; schema v2 adds `invocation_mode`, `description`, `allowed_tools`, and hash-pinned `resources`.
- Invocation modes are `automatic` (trigger-matched), `user_invocable` (explicitly selected), and `always_apply` (attached only to mapped roles).
- Every Skill and bundled resource is pinned by SHA-256 and checked at load and again before context use. Paths must remain inside the package root.
- Only the main `SKILL.md` and explicitly typed `reference` files enter model context. `script` and `asset` resources are inert, are never executed, and are not injected.
- `allowed_tools` is descriptive metadata only. It never installs or authorizes an MCP tool; adapter verification, role permissions and host approvals remain authoritative.
- Selection limits: 4 requested Skills, 8 applied Skills, 32 resources per Skill, 256 KiB per resource, and 64 KiB of context per Skill.

Example authenticated request:

```json
{
  "agent_id": "maintenance-engineer",
  "objective": "Review the preventive-maintenance checklist",
  "skill_ids": ["maintenance-checklist"]
}
```

## Governed MCP adapter boundary

The v8.1 branch adds an in-process MCP adapter contract and an authenticated metadata catalog at GET /v1/mcp/tools. Adapters must match a reviewed capability record by source URL, publisher, version, content digest, permission scopes and data-access scopes. A capability must be installed, explicitly enabled and revalidated before each call.

Tool calls are role-scoped, permission-checked and bounded by JSON input/result sizes and a deadline. Audit events store hashes and safe metadata rather than raw arguments or results. A timeout is not retried automatically and only signals cooperative cancellation; Python cannot forcibly stop an already-running in-process adapter. Privileged MCP tools are rejected until durable approval/replay storage is verified, so this branch must not register write-capable adapters.

**Important:** this is an adapter boundary, not a remote MCP client. It does not discover or connect to external MCP servers, and no third-party tool is enabled by default. CI uses deterministic fake adapters.

## Bounded specialist delegation

The Coordinator exposes a bounded subagent workflow through POST /v1/subagents/run and its internal run_subagents method. A parent may delegate up to three sequential child tasks. Each child has:

- Its own task ID and role-specific memory namespace.
- Only the explicitly supplied JSON inputs; parent conversation and private context are not copied automatically.
- A maximum of four steps, a bounded deadline and a role handoff check.
- A deterministic parent-scoped idempotency key prevents duplicate child invocations when the same delegation is retried.
- A persisted parent_task_id and a concise result summary returned to the parent.

The maximum configured delegation depth is three. Cycles, unauthorized handoffs, oversized inputs and budget overflow fail closed. Parent approval never grants a child broader permissions. This release does not run child tasks in parallel or retry failed child runs automatically.

## Resumable task event reads

Authenticated GET /v1/tasks/{task_id}/events?after={event_id} returns ordered, bounded event pages from SQLite or PostgreSQL. The response includes next_cursor and has_more. A client reconnects by supplying the last received event ID; this only reads persisted history and never re-executes the task.

The command center includes a basic visual trace panel. Live streaming and detailed provider token/cost views remain future work. Cost is recorded only when an actual provider reports it or the runtime measures it; unknown values are not fabricated.

## Security and approval boundary

- One bearer-token boundary protects all `/v1/*` APIs.
- Provider keys and database credentials remain server-side.
- The browser cannot read or write database tables directly.
- All task execution passes through the Coordinator and permission policy.
- The approval ledger binds a one-use approval ID to an action digest and consumes it atomically.
- Consequential execution remains disabled until authenticated approval, transaction/replay, backup and restore tests all pass and the owner separately approves activation.
- A capability catalogue record is not proof that an integration is installed or authorized.

## Verification

Run the full suite:

```bash
python -m compileall -q unexpected_runtime
python -m unittest discover -s tests -v
```

The deployment contract tests assert one Python process, one Render web service, a `/health` check, PostgreSQL fail-closed behavior, and no phone/PWA assets in the v8 web tree.

## Migration and rollback

The original AI Studio repository and both old Render services remain untouched during migration. The v8 service must pass preview, provider, database, lifecycle, backup/restore and rollback checks before cutover. Retiring either old service is a separate operation requiring explicit final confirmation.

## Resource Intelligence and AI quality

The versioned catalog in `unexpected_runtime/data/resource_catalog.json` indexes [sindresorhus/awesome](https://github.com/sindresorhus/awesome) as a permanent discovery source. Linked repositories are separate candidates: their license, maintenance, dependencies and security posture are not inherited from the list. Catalog states distinguish discovered, triaged, verified, approved and integrated. No catalog read installs or authorizes a tool.

The authenticated command center exposes `GET /v1/resources`, `GET /v1/quality-evaluations` and the owner-initiated `POST /v1/quality-evaluations`. The CLI exposes `resources` and `quality-eval`. Quality runs are bounded to the versioned scenario set, use only a configured and verified non-mock provider, and request no privileged permissions. Reports retain case outcomes and output digests rather than duplicating raw output. Fixture/offline CI tests are labelled separately from live provider runs. There is no background catalog crawler, package installer, LLM-as-judge or automatic improvement promotion.


## Native uneXpected Video Engine (draft PR #20)

The native Video Engine is part of the existing Python runtime. It reuses the existing Coordinator, 38-role registry, CapabilityRegistry, MCPToolGateway and shared SQLite/PostgreSQL state. It does not add a second CRM, coordinator, agent registry, database or public video SaaS service.

The current implementation includes:
- A durable, idempotent media-job queue and additive PostgreSQL migration 004 (after Prompt Intelligence migration 003).
- A pinned OpenFilm 0.2.7 Node runner, local worker Containerfile and rootless Podman isolation contract.
- Relative project-path and symlink checks, per-job resource ceilings, lease fencing and one-job worker execution.
- FFprobe/FFmpeg checks for MP4 streams/profile, duration, audio coverage/loudness/true peak when required, black frames, freezes, captions and a contact sheet.
- A portable artifact manifest containing source/project/output hashes, renderer version, rights-manifest hash and QA results.
- Authenticated media status/job APIs, cancellation, CLI lifecycle/preflight/one-shot worker commands and a Video Engine command-center view.

The capability starts as discovered. It is not automatically installed or enabled. To use it, review the pinned source, build the local worker image, set the explicit host/job limits from .env.example, run the local media preflight, then explicitly review/install/enable it. The full procedure is in workers/openfilm/WORKER-SETUP.md. Do not use the Render Free service as the Chromium/FFmpeg worker host.

**Important limits:** no live render or final MP4 is verified yet; the local worker host is not configured by this repository change. The renderer composes supplied project assets—it does not yet provide built-in realistic TTS, licensed music, original footage generation or publishing. Every final master still requires human playback/listening review and a separate publishing approval. Everygen is not a required dependency; external generation providers remain optional adapters.
