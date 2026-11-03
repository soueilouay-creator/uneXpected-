# OpenFilm Production Capability — uneXpected v8.1 Design Specification

**Status:** Architecture approved; specification prepared for owner review  
**Date:** 2026-11-03  
**Repository:** soueilouay-creator/uneXpected-  
**Base branch:** feat/v8.1-runtime-intelligence  
**Feature branch:** feat/openfilm-production-capability  
**Scope:** Add a governed, optional video-production capability to the existing uneXpected runtime. This document does not authorize production deployment, public publishing, paid generation, or activation of the capability.

## 1. Goal and non-goals

### Goal

Add a reproducible, editable video-production path to the existing uneXpected creative-media workflow. uneXpected remains the sole coordinator and source of workflow state. OpenFilm supplies the local film-project format, timeline, deterministic rendering and visual/audio inspection. Metricool remains the existing distribution and scheduling system. The sales workflow continues to measure qualified enquiries, demonstrations and evidenced revenue.

The intended flow is:

Request → Creative plan → Editable film project → Queued render job → OpenFilm render and inspection → Additional technical QA → Human review → Existing authorized Metricool workflow → Evidence-linked sales monitoring.

### Non-goals

- Do not add another agent, coordinator, command center, public API, database, scheduler or standalone publishing product.
- Do not replace Metricool, Gmail, the Sales Control Center, or the existing 38-role registry.
- Do not add the phone/PWA application or revive the separate AI Studio gateway.
- Do not run arbitrary shell commands, arbitrary coding-agent tools, or user-supplied scripts on the runtime host.
- Do not call OpenFilm provider integrations for generated voice, music, images or video in the first release.
- Do not publish, upload, schedule, reply, DM, submit forms, spend money, or access customer accounts as a consequence of a successful render.
- Do not deploy the renderer to the current Render Free service or claim that the current hosted environment can render videos.

## 2. Verified source and dependency baseline

OpenFilm source reviewed: https://github.com/openfilm/openfilm

- Release: v0.2.7.
- Release tag object: 5d47f6915d8c325856f76d0157b3c0a8904d03e0.
- Tag target commit: b7673b585e3e9c3b434fe663e68619cc1984ae8b.
- OpenFilm package version in package metadata: 0.2.7.
- License: MIT. Preserve the upstream copyright and license notices in any redistributed copy.
- Provenance note: the v0.2.7 annotated tag reports an unsigned tag. Pin the exact target commit, verify npm package-lock integrity and license contents during installation, and do not follow a floating latest tag.
- The OpenFilm monorepo declares Node >=22.18 and pnpm 9.15.9; the openfilm package itself declares Node >=22.2. Use Node >=22.18 for the worker baseline.
- OpenFilm’s project protocol is documented as draft 0.1. Treat its public package exports and version-pinned behavior as the integration contract; do not depend on private implementation paths.

Useful upstream interfaces reviewed:
- Public package exports include look and render.
- look returns a structured success value, diagnostic lines and generated inspection files. Its implementation checks deterministic frame output, render/frame errors, fonts, missing media, text clipping and timeline issues.
- render accepts a project and render options, writes an encoded video and supports explicit output paths and bounded rendering options.
- OpenFilm’s command-line open path may start Studio for interactive review. The uneXpected worker must call the package APIs directly and must not invoke the interactive open command.
- OpenFilm’s own service is intended to listen on loopback only. Do not expose Studio or its local project server to the public internet.

## 3. Architecture

### Runtime remains authoritative

The current v8.1 branch already includes:
- One Python HTTP application and Coordinator.
- One capability registry and permission policy.
- The governed MCP-compatible adapter boundary.
- SQLite for local development and PostgreSQL for hosted shared state.
- A hash-pinned creative-media Skill bundle and the existing creative-media-studio workflow.

Extend these components rather than creating a parallel system. Use the existing StateStore as the only authoritative queue and event store. Media files are artifacts, not a second state database.

### Asynchronous render boundary

The MCP boundary has a maximum synchronous tool timeout of 60 seconds. A video render may take longer. Therefore, MCP tools must only enqueue, inspect or cancel a media job; they must never render a complete film synchronously.

A bounded media worker claims queued jobs from the same StateStore and invokes an allowlisted Node runner. The worker is an optional process of the same uneXpected installation, not a new public service and not an autonomous agent. The initial operator interface is a one-job command that claims at most one job and exits. No automatic recurring worker schedule is introduced by this feature.

The worker must run only on a host with sufficient verified CPU, memory, storage and browser isolation. It must not be enabled on the current Render Free service.

### OpenFilm is a renderer, not a provider router

The first release uses only locally supplied or already-authorized source media and deterministic web-scene animation. OpenFilm generation commands that connect to ElevenLabs, OpenAI, Google, fal or other providers remain unavailable. No API keys are passed to the worker. Any later provider integration requires a separate cost, rights, credential, quota and approval review.

## 4. Proposed components and file responsibilities

Paths below are proposed additions or modifications on the feature branch. Exact implementation may be refined after the spec is approved.

### Python runtime

- Create **unexpected_runtime/media/__init__.py** for media capability package exports.
- Create **unexpected_runtime/media/openfilm_adapter.py** implementing the existing MCPAdapter contract. It exposes only enqueue, status and cancel operations. It does not run FFmpeg or Chromium.
- Create **unexpected_runtime/media/jobs.py** for media-job records, state transitions, idempotency, leases and artifact metadata using the existing StateStore.
- Create **unexpected_runtime/media/worker.py** for one-job claim, bounded subprocess lifecycle, cancellation, timeout, output verification and completion recording.
- Create **unexpected_runtime/media/paths.py** for job-root resolution, symlink rejection, safe relative paths and output containment.
- Create **unexpected_runtime/media/qa.py** for post-render FFprobe and FFmpeg checks, report normalization and SHA-256 manifests.
- Create **unexpected_runtime/cli_media.py** or extend the current CLI with read-only capability status and an explicit one-job worker command.
- Modify **unexpected_runtime/storage.py** and **unexpected_runtime/postgres_storage.py** to implement the same media-job storage contract.
- Create additive migration **migrations/003_openfilm_media_jobs.sql** after comparing against the latest branch schema and the isolated test database. Do not modify the parent Neon schema or production database.
- Modify **unexpected_runtime/capabilities.py** only to register and verify the OpenFilm capability using the existing lifecycle. A capability record being discovered or installed must not make its adapter callable.
- Modify the existing MCP boundary only if an adapter contract gap is demonstrated by tests. Preserve its current input/output byte limits, permission checks, deadline handling and audit behavior.

### Pinned Node runner

- Create **workers/openfilm/package.json** with an exact OpenFilm dependency version of 0.2.7.
- Commit a generated package-lock file with its resolved package integrity.
- Create **workers/openfilm/run-job.mjs** as a narrow JSON-in/JSON-out runner. It imports only OpenFilm’s public look and render exports, runs the inspection before render, renders to a unique job-specific temporary output, and returns a bounded result manifest.
- Use explicit argument/data contracts; do not invoke a shell, accept arbitrary executable paths from the job payload, use npx @latest, invoke the interactive Studio command, or execute arbitrary project files in Node.
- Install FFmpeg and the Playwright Chromium runtime in the worker image or host setup, not in the primary uneXpected application image.

### Creative workflow and docs

- Update **skills/creative-media/WORKFLOW.md** and its hash-pinned manifest entry without adding a specialist role.
- Update **workflow_profiles/creative-media-studio.md** with OpenFilm route selection, render-job lifecycle, limits and handoff requirements.
- Update **CAPABILITY_MATRIX.md**, **README.md**, **CHANGELOG.md**, relevant setup documentation and **FILE_INVENTORY_SHA256.txt**.
- Preserve upstream MIT notices. Do not use OpenFilm’s logo or imply endorsement; describe the capability as “rendered with OpenFilm” only where accurate.

## 5. Capability and permission model

Create a provenance-backed capability record with:
- ID: **media.openfilm.render**.
- Provider: **openfilm**.
- Adapter type: **mcp**.
- Source URL: https://github.com/openfilm/openfilm
- Pinned release and source commit from Section 2.
- Publisher: OpenFilm contributors.
- Dependency evidence: Node, FFmpeg, Playwright Chromium and package-lock integrity.
- Data access: only the isolated job project and output directories.
- Cost notes: core rendering is local and does not itself require a paid generation provider; compute, disk and network setup still consume host resources.
- Risk notes: generated HTML/JavaScript executes in a browser; untrusted projects must be sandboxed and network restricted.
- Initial lifecycle state: **discovered**. Do not mark reviewed, installed or enabled before their specific evidence gates pass.

Expose only these logical tools:
- **openfilm.job.create**: validate and enqueue a render/inspection job; return stable job ID and current state.
- **openfilm.job.status**: return bounded state, progress, QA summary, artifact hashes and failure category.
- **openfilm.job.cancel**: request cancellation of a queued or processing job; cancellation is confirmed only after the worker records it.

Allowed caller roles are limited to the orchestrator and creative-media roles that need production: **orchestrator**, **creative-director**, **media-producer**, and **voice-agent**. The tool descriptor’s role list is not permission by itself. The runtime PermissionPolicy must explicitly permit the relevant non-consequential local media scope. Publishing, uploading, external messaging and paid provider scopes are not included.

No role receives a raw shell, filesystem-wide access, general Node execution or arbitrary OpenFilm command access.

## 6. Media-job data contract and state machine

A media job contains:
- Stable **job_id**, originating **task_id**, campaign ID and content source code.
- Requesting role, creation time, idempotency key and pinned capability version.
- Project path relative to a configured job root; never accept an arbitrary absolute path.
- Requested variant metadata: platform, width, height, frame rate, duration ceiling and subtitle language tracks.
- Synthetic-data flag and rights/source manifest.
- State, attempt count, lease owner/expiry, cancellation request and bounded progress.
- Output paths relative to the artifact root, file sizes, SHA-256 hashes, technical QA report and failure category.
- Created/updated timestamps and provenance for every state transition.

State transitions:

**queued → claimed → inspecting → rendering → post_render_qa → ready_for_human_review**

Failure paths:
- Any stage may transition to **failed** with a bounded error category and safe diagnostic.
- A technical defect transitions to **qa_blocked**, not ready.
- A cancellation request transitions to **cancel_requested**; terminal **cancelled** is recorded only when the worker has stopped and cleaned temporary resources.
- A worker lease that expires may be reclaimed only after fencing the prior worker and inspecting whether an output already exists. A retry must not overwrite a verified artifact.

The **ready_for_human_review** state is not an approval to publish. Existing creative-media states continue separately: human review, upload, schedule and publication each need their own evidence. Metricool publication remains outside this adapter.

Storage requirements:
- SQLite and PostgreSQL implementations must share the same contract.
- Job creation is idempotent on task ID + request idempotency key.
- PostgreSQL claims must be transactional and single-flight. SQLite claims must be atomic under the existing supported transaction model.
- Store metadata, hashes and state in StateStore. Store large media bytes in the configured artifact directory, not database rows.
- Use a unique temporary output per job and atomic finalization after QA. Never use an overwrite option against an existing user artifact.
- A worker must not report success until the file exists, is non-empty, is within configured size limits, has the expected container/streams and its SHA-256 has been read back.

## 7. Worker execution and security

The worker must:
- Run as an unprivileged OS user or rootless container.
- Execute a fixed, version-pinned Node runner with a fixed working directory and **shell=False**.
- Receive only a minimal allowlisted environment. Do not inherit OpenRouter, OpenOx, OpenAI, Anthropic, Gmail, Metricool or runtime bearer credentials.
- Set explicit job timeout, memory/CPU limits, maximum project bytes, maximum asset count and maximum output bytes.
- Use a unique temporary job directory; reject path traversal, symlinks escaping the job root, hidden runtime directories, device files and unsupported media types.
- Treat film.html, scene HTML/JS/CSS, subtitles, asset metadata and upstream prompts as untrusted.
- Run OpenFilm inspection/render in offline mode by default. Permit no external origin by default; any future asset origin allowlist must be per-job, explicit, reviewed and recorded.
- Ensure the rendered page can reach only the OpenFilm project’s own loopback origin, not unrelated loopback ports, host metadata endpoints, the public internet, or host file paths.
- Keep Studio, its preferences and the OpenFilm media-provider settings out of the hosted command center. Do not expose OpenFilm’s local server to a public interface.
- On timeout or cancellation, terminate the whole child-process tree, including Chromium and FFmpeg; remove only that job’s temporary files.
- Return bounded output and diagnostics. Never log raw credentials, raw provider payloads, customer media or full project contents.
- Never place real customer machine, employee, supplier or operational data in sample scenes unless the customer explicitly authorized its use. Default demo data is clearly marked synthetic.

A worker that cannot prove its network restriction, process isolation and resource limits remains disabled.

## 8. Rendering and quality requirements

### Editable project and master outputs

The canonical deliverable is an editable OpenFilm project folder containing film.html, scene pages and required local assets, plus a rendered MP4 and a machine-readable QA manifest. Preserve an English caption track and any requested French/Arabic subtitle tracks as separate files where available. Keep captions editable; do not burn them into the master unless a specific approved platform variant requires it.

Initial platform variants:
- YouTube Shorts: portrait 1080×1920 master.
- TikTok: portrait 1080×1920 variant, with text/CTA placement checked against platform interface safe areas.
- YouTube long-form: landscape 1920×1080 variant when the brief requires it.

The same source project may produce multiple aspect-ratio variants, but each variant must be inspected independently. Platform dimensions are requirements for this project, not a statement that every platform accepts every codec or duration.

### Required automated checks

1. OpenFilm look succeeds before render and its error list is empty.
2. OpenFilm renders through its public package API at a deterministic pinned version.
3. FFprobe verifies MP4 container, video stream, dimensions, frame rate, duration and expected audio stream presence.
4. If audio is required, verify its duration covers the intended film, no missing source files, no unexpected silent gaps, loudness within the declared delivery target and true peak below the project ceiling.
5. Run FFmpeg black-frame and freeze-frame detection; report timestamps and fail on defects beyond approved thresholds.
6. Inspect sampled frames/contact sheet for text clipping, contrast, CTA legibility, layout continuity and obvious missing media.
7. Validate subtitle syntax, monotonic timestamps, bounds within film duration, language metadata and synchronization tolerance where transcript timing is available.
8. Record source/project/output SHA-256, OpenFilm version, render settings, QA tool versions and each check’s pass/fail result.

Automated checks do not replace human end-to-end video and audio review. The output is **ready_for_human_review**, never **published**, after automated QA passes.

### Campaign consistency

Use **MAINTENANCE_TRACKER_GROWTH** and the existing **YT-TRACKER-xx** source codes. Preserve already approved/scheduled content CTAs; do not edit or duplicate existing posts. New Shorts should use the approved truthful CTA “Comment TRACKER for details” unless a later approved brief says otherwise. Match every video to one maintenance pain point, one target buyer and one verified offer. Product feature claims must be checked against the actual workbook.

## 9. Integration with Metricool and sales

The OpenFilm capability ends at a customer-reviewable artifact and content manifest.

The manifest carries content ID, campaign ID, platforms, title/description/CTA drafts, captions, file hashes, rights/source notes and QA outcome. The existing creative workflow then presents the exact files and metadata to the authorized publishing workflow. No Metricool upload or schedule operation is invoked by this capability.

After publication, the existing YouTube/TikTok monitoring workflows may record actual returned video IDs, URLs, publication dates and analytics. A comment or DM counts as a lead only when its content is available and shows relevant enquiry intent. Views and likes are engagement metrics, not leads. Sales replies, demos and revenue continue to require direct evidence. No automatic public reply, DM, email, quote or form submission is added.

## 10. Resource and deployment boundary

The connected Render v8 test service currently uses the Free plan. Render metrics returned a memory limit of 536,870,900 bytes (approximately 512 MiB) and a CPU limit of 0.15. Chromium plus FFmpeg and a film project can exceed that envelope or starve the Python command center.

Therefore:
- Do not add Node, FFmpeg, Chromium or OpenFilm to the main uneXpected Docker image.
- Do not start a Render background worker or second public service.
- Do not render videos on the current Render Free service.
- First validate a one-shot local worker on a resource-appropriate host with persistent local artifact storage.
- Keep the hosted v8 capability metadata visible as discovered/installed/unavailable until a real worker registration and self-test succeeds.
- No persistent remote artifact store is assumed. A local artifact path is not a hosted public URL and is not automatically accessible to Metricool.
- Any later hosted worker or object-store integration is a separately reviewed architectural change with a proven $0 operating path and tested persistence/recovery.

## 11. Testing and acceptance gates

### Unit and contract tests

- Capability lifecycle: discovered cannot execute; installation alone cannot enable; only a verified worker may enable the capability.
- MCP tool boundary: role, permission, payload size, deadline and approval policies remain enforced; enqueue/status/cancel return within the boundary timeout.
- Job store: create idempotency, single-flight claims, leases, fencing, cancellation, stale-worker recovery, retry and terminal states.
- Paths: traversal, symlink escape, hidden files and arbitrary absolute paths are rejected.
- Runner: fixed binary, fixed version, fixed arguments, no shell, no inherited secrets, bounded stdout/stderr and process-tree cleanup.
- QA: missing MP4, zero-byte output, wrong dimensions, no expected audio, out-of-range duration, black/frozen frames, malformed captions and hash mismatch fail closed.
- Security: fixture scenes cannot access public internet, host metadata, unrelated loopback services, environment secrets or files outside the job root.
- Regression: no change to the 38-role registry, coordinator lifecycle, approval ledger, phone/PWA exclusion, provider selection or existing creative workflow semantics.

### End-to-end pilot

Create a short, original industrial-maintenance explainer using only synthetic data and locally supplied assets. Do not require any paid provider. Produce:
- Editable OpenFilm project.
- Portrait YouTube Shorts render.
- Portrait TikTok render.
- English captions and a French subtitle track if timing is verified.
- Automated QA manifest and checksums.
- Human-review checklist.

The pilot passes only if the actual MP4s are opened and checked, full soundtrack is listened to, frames/transitions/captions are reviewed, no unintended black/frozen frames are found, and all outputs are reproducible from the pinned project. A script or project folder alone is not a finished video.

### Release gates

1. Specification approved by owner.
2. Implementation plan approved and tests demonstrate red before green for each behavior.
3. Local fake-worker tests pass.
4. Pinned OpenFilm package install, doctor, look, and render pass on the target host.
5. Security/network-isolation and resource-limit checks pass.
6. Actual pilot MP4 and editable project pass technical and human QA.
7. Output read-back, hashes, rollback candidate and worker recovery test pass.
8. Capability transitions to enabled only after all relevant evidence is recorded.
9. Deployment, Metricool upload, scheduling or publication requires separate explicit approval and is outside this release.

## 12. Rollback and failure behavior

- Disable the capability and stop claiming media jobs if the worker self-test, storage, dependency pin, security check or resource budget fails.
- Preserve the last verified project and artifacts; never overwrite them during retries.
- Mark unfinished jobs blocked/failed and resume from the first unverified stage on the next explicit worker run.
- Keep upstream OpenFilm package and all job data outside the main app image so removing the optional worker does not affect the command center.
- Roll back only the feature branch or its isolated commits; do not alter v8.1 base, main, Render services, old services or production databases.
- Never treat a timeout, missing callback or lost connection as proof that a render did not complete. Inspect the job record and artifact path before any retry.

## 13. Unresolved decisions for the implementation plan

These decisions affect deployment and must be resolved with evidence rather than assumed:
1. Which persistent, resource-appropriate local machine/host will run the first OpenFilm worker? The current Render Free host is explicitly excluded.
2. Which durable artifact handoff will make locally rendered files available to the existing Metricool workflow without assuming a public URL or adding a paid storage service?
3. What concrete CPU, memory, project-size and render-time limits can the selected worker host actually enforce?

Until these decisions are tested, the capability remains unavailable for unattended production. The approved design permits a local, one-job pilot after the owner has reviewed this specification and the implementation plan.
