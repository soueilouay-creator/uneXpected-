# OpenFilm Production Capability Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional, reproducible OpenFilm render pipeline to the existing uneXpected v8.1 runtime, ending at a technically checked artifact awaiting human review.

**Architecture:** uneXpected remains the only coordinator, capability registry, permission authority and StateStore. Its existing MCP adapter boundary will enqueue, inspect and cancel jobs; a one-job worker on a separately verified local host will call a pinned Node/OpenFilm runner and write large artifacts to a configured local artifact root. Metricool and the Sales Control Center remain separate downstream workflows, and this feature will not publish or message externally.

**Tech Stack:** Python 3.12 runtime; existing SQLite and PostgreSQL StateStore implementations; additive PostgreSQL migration 003; Node.js >=22.18; exact OpenFilm 0.2.7 package pin and npm lockfile; Playwright Chromium; FFmpeg/FFprobe; Python unittest; Node's built-in test runner.

## Global Constraints

- Preserve one uneXpected coordinator, one 38-role registry, one permission policy, one StateStore and one public HTTP API. Do not add another agent, coordinator, database, public API, scheduler, command center, Render service or phone/PWA application.
- Reuse the existing MCP protocol in unexpected_runtime/mcp/protocol.py and MCPToolBoundary in unexpected_runtime/mcp/boundary.py. Its tool timeout is capped at 60 seconds. MCP operations are limited to create/enqueue, status and cancel; no tool call may perform a full render.
- Use the existing SQLite StateStore for local development and PostgreSQL StateStore for hosted shared state. Media metadata, leases, transitions, hashes and audit events live in that StateStore. Large project and output files live only under a configured artifact root.
- Pin OpenFilm to version 0.2.7 and source target commit b7673b585e3e9c3b434fe663e68619cc1984ae8b. Verify npm package-lock integrity and preserve the upstream MIT license and copyright notices. Use Node >=22.18. Do not use a floating tag, npx @latest, private OpenFilm imports or the interactive Studio/open command.
- Do not pass provider credentials, uneXpected bearer tokens, database credentials, Metricool/Gmail credentials or any inherited secret to the worker. Do not enable OpenFilm's remote generation/provider integrations in this release.
- Treat film.html, scene HTML/JS/CSS, prompts, subtitles, asset metadata and supplied media as untrusted. Worker execution is unprivileged, fixed-path, shell-free, resource-bounded and network-denied by default. The worker must fail closed if its host cannot prove the configured isolation and limits.
- The current Render Free command-center service is not a render host. Do not add Node, FFmpeg or Chromium to the main uneXpected Docker image, and do not create a Render background worker.
- A discovered or installed capability is not callable. The OpenFilm capability starts discovered and stays unavailable until source, dependency, worker and isolation evidence is reviewed and its adapter is verified. The tool descriptor's role list does not grant permission.
- Only orchestrator, creative-director, media-producer and voice-agent may receive the non-consequential media.local_render scope. No publish, upload, schedule, email, DM, public reply, paid-provider, account-change or other consequential scope is added.
- Preserve the state flow queued → claimed → inspecting → rendering → post_render_qa → ready_for_human_review. Failed, qa_blocked, cancel_requested and cancelled paths must be explicit. A passing automated QA report is not human approval and is never publication authorization.
- Use unique per-job/per-attempt temporary output paths and no-overwrite finalization. Never replace a verified user artifact during a retry. A stale worker must be fenced before a replacement attempt can advance state.
- The initial outputs are an editable project, YouTube Shorts portrait 1080×1920, TikTok portrait 1080×1920 and, only when requested, YouTube landscape 1920×1080. Inspect every aspect-ratio variant independently.
- Campaign continuity is MAINTENANCE_TRACKER_GROWTH and existing YT-TRACKER-xx source IDs. Do not edit or duplicate already approved or scheduled content. For new Shorts, use “Comment TRACKER for details” unless a newer approved brief supersedes it. Verify all product claims against the actual workbook.
- The capability stops at a customer-reviewable artifact and manifest. No Metricool upload/schedule, YouTube/TikTok publication, public reply, DM, email, quote, form submission, customer-account write or paid action is performed.
- Views and likes are engagement, not leads. Only actual, evidenced relevant enquiries, sales replies, booked demos and revenue can be written into the existing Sales Control Center.
- Rollback is limited to the isolated feature branch and its own artifacts. Do not change the base branch, main, production database, Render settings or legacy services as part of this feature.

---

### Task 1: Add the durable media-job contract to the existing StateStore

**Files:**
- Create: unexpected_runtime/media/__init__.py
- Create: unexpected_runtime/media/jobs.py
- Modify: unexpected_runtime/storage.py — SQLite schema initialization and StateStore methods
- Modify: unexpected_runtime/postgres_storage.py — PostgreSQL StateStore methods
- Create: migrations/003_openfilm_media_jobs.sql
- Create: tests/test_media_jobs.py
- Modify: tests/test_postgres_storage.py
- Modify: tests/test_postgres_integration.py
- Modify: tests/test_deployment_contract.py

**Interfaces:**
- Create in unexpected_runtime/media/jobs.py:
  - MediaJobState: the finite state values listed in Global Constraints.
  - MediaJobConflict: idempotency key reused with a different request digest.
  - MediaJobService(store): create(), get(), list(), cancel(), claim_one(), advance(), and recover_expired().
- Both StateStore implementations must expose the same persistence methods:
  - create_media_job(record: dict) -> dict
  - get_media_job(job_id: str) -> dict | None
  - list_media_jobs(limit: int = 100, state: str | None = None) -> list[dict]
  - claim_media_job(worker_id: str, lease_seconds: float) -> dict | None
  - transition_media_job(job_id: str, expected_state: str, target_state: str, *, worker_id: str | None, lease_token: str | None, patch: dict | None = None) -> bool
  - request_media_job_cancel(job_id: str) -> str | None
  - recover_expired_media_job(job_id: str, old_lease_token: str, worker_id: str, lease_seconds: float, recovery_action: str) -> dict | None
- A stored job record contains job_id, task_id, idempotency_key, request_sha256, request_json, state, attempt_count, lease_owner, lease_token, lease_expires_at, cancel_requested, result_json, created_at and updated_at. Relative project/artifact paths and requested variant data are stored in request/result JSON, not as arbitrary absolute paths.
- create() canonicalizes finite JSON, hashes the request, and uses task_id + idempotency_key as the unique key. A repeated identical request returns the original job; reuse of the same key with a different digest raises MediaJobConflict.
- claim_media_job() is single-flight and atomically claims only a queued job, assigns a fresh unpredictable lease token and expiry, and increments attempt_count. PostgreSQL uses a transactional row lock / SKIP LOCKED strategy; SQLite uses a write transaction that prevents competing claimers.
- Every worker transition is compare-and-set on job_id, expected state, worker_id and current lease token. A stale token cannot advance, fail, cancel or finalize a newer attempt.
- Queued cancellation records cancelled immediately. A claimed or processing job records cancel_requested; the worker records cancelled only after its child process has stopped and its temporary output is no longer being written.
- Expired-lease recovery requires an explicit recovery_action. “retry” fences the old token and creates a new attempt namespace; “qa_existing_output” fences the old token and advances only to post_render_qa after the existing final output has been independently identified. Neither action overwrites an existing output. Partial old-attempt directories are quarantined until the old process is known to have stopped.
- Only these state transitions are accepted: queued→claimed/cancelled/failed; claimed→inspecting/cancel_requested/failed; inspecting→rendering/cancel_requested/failed/qa_blocked; rendering→post_render_qa/cancel_requested/failed/qa_blocked; post_render_qa→ready_for_human_review/cancel_requested/failed/qa_blocked; cancel_requested→cancelled/failed. ready_for_human_review, failed, qa_blocked and cancelled are terminal for automatic worker retries.
- Each accepted state change is paired with an audit event containing bounded identifiers, state names, attempt number and digest metadata; it must not include full project content, customer media or secrets.

- [ ] **Step 1: Add focused failing storage tests**

Add assertions for: exact duplicate request replay; same task/key with changed digest conflict; 20 concurrent claim attempts yielding exactly one claimant; stale lease token unable to transition; expired lease recovery rotating the token; queued cancellation becoming cancelled; running cancellation becoming cancel_requested; invalid transition rejection; filtered job listing; and reopening SQLite preserving job state and result metadata.

Extend the fake PostgreSQL tests to assert equivalent method behavior and schema version 3. Extend the PostgreSQL integration test, guarded by TEST_POSTGRES_DSN, to make concurrent claim attempts against a uniquely named test job and assert exactly one owner.

- [ ] **Step 2: Verify the relevant failure**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_media_jobs.py' -v
python -m unittest discover -s tests -p 'test_postgres_storage.py' -v
~~~
Expected: the new tests fail because MediaJobService, media-job persistence methods and migration version 3 do not yet exist; existing tests remain discoverable.

- [ ] **Step 3: Implement the minimum storage behavior**

Add the finite state model and service in unexpected_runtime/media/jobs.py. Add the SQLite table and indexes in StateStore._init(). Add only additive DDL and schema_migrations version 3 in migrations/003_openfilm_media_jobs.sql. Add equivalent PostgreSQL statements and transactional methods in PostgresStateStore. Keep SQLite and PostgreSQL method names and returned record shapes identical. Do not modify migrations 001 or 002, and do not apply migration 003 to any connected production database.

- [ ] **Step 4: Verify the focused pass**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_media_jobs.py' -v
python -m unittest discover -s tests -p 'test_postgres_storage.py' -v
~~~
Expected: all media-job unit tests and fake-PostgreSQL contract tests pass, including concurrency, idempotency, lease fencing and cancellation assertions.

- [ ] **Step 5: Run the affected integration check**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_deployment_contract.py' -v
TEST_POSTGRES_DSN=<isolated-test-database-dsn> python -m unittest discover -s tests -p 'test_postgres_integration.py' -v
~~~
Expected: migration 003 is additive and versioned; the isolated PostgreSQL suite passes against a throwaway test database. If TEST_POSTGRES_DSN is absent, the PostgreSQL integration test remains explicitly skipped; never substitute a production DSN.

- [ ] **Step 6: Commit the passing deliverable**

~~~bash
git add unexpected_runtime/media/__init__.py unexpected_runtime/media/jobs.py unexpected_runtime/storage.py unexpected_runtime/postgres_storage.py migrations/003_openfilm_media_jobs.sql tests/test_media_jobs.py tests/test_postgres_storage.py tests/test_postgres_integration.py tests/test_deployment_contract.py
git commit -m "feat(media): add durable OpenFilm job state"
~~~

---

### Task 2: Add the governed OpenFilm adapter and Coordinator wiring

**Files:**
- Create: unexpected_runtime/media/openfilm_adapter.py
- Modify: unexpected_runtime/coordinator.py
- Modify: agent_manifest.json
- Modify: tests/test_mcp_boundary.py
- Create: tests/test_openfilm_adapter.py
- Modify: tests/test_capabilities.py
- Modify: unexpected_runtime/cli.py

**Interfaces:**
- OpenFilmAdapter(store, job_service, capability_record, worker_readiness) implements the existing MCPAdapter protocol: describe() and call(tool_id, arguments, context).
- It exposes exactly three ToolDescriptor IDs:
  - openfilm.job.create
  - openfilm.job.status
  - openfilm.job.cancel
- create accepts a project path relative to the configured project root, campaign/content identifiers, source/rights manifest, synthetic-data flag and requested render variants. It returns only job_id, state and whether the request was replayed.
- status accepts job_id and returns bounded state, attempt/progress metadata, QA summary, artifact hashes and a safe failure category. It does not return full filesystem contents or project HTML.
- cancel accepts job_id and returns cancelled or cancel_requested as recorded by StateStore. It never reports cancellation complete while a child process is still running.
- Tool calls use a bounded short timeout (10 seconds is the initial engineering recommendation; final descriptor values must remain below the existing 60-second boundary maximum). They perform no render, FFmpeg, Chromium, network or provider operation.
- Add media.local_render to allowed_permissions only for orchestrator, creative-director, media-producer and voice-agent in agent_manifest.json. No other role receives it. PermissionPolicy remains authoritative; the descriptor role list is not a substitute for the scope check.
- Coordinator owns the single CapabilityRegistry and MCPToolBoundary instance used by this feature. Do not add HTTP routes. Existing /v1/capabilities remains metadata-only and read-only.
- Capability record ID is media.openfilm.render, provider openfilm, adapter type mcp, source https://github.com/openfilm/openfilm, version 0.2.7 and source/package digest evidence. It is registered in discovered state. Adapter registration is refused unless the capability is enabled and the adapter verifier proves the reviewed worker bundle is the one being used.
- Add a read-only CLI status command under the existing CLI (python -m unexpected_runtime.cli media status). It reports capability state and worker readiness; it does not install, enable, run or schedule a worker.

- [ ] **Step 1: Add focused failing adapter and permission tests**

Test exact descriptor IDs and provenance; reject unknown tool IDs; reject all roles except the four approved IDs; reject a caller lacking media.local_render; reject a discovered or merely installed capability; reject a mismatched adapter digest; reject project traversal/absolute paths; verify create returns immediately without launching a renderer; verify status is bounded; verify cancellation is confirmed only from the persisted state; and verify the new CLI status path does not mutate capability state.

- [ ] **Step 2: Verify the relevant failure**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_openfilm_adapter.py' -v
python -m unittest discover -s tests -p 'test_mcp_boundary.py' -v
~~~
Expected: the new tests fail because the adapter and Coordinator wiring are absent and the role manifests do not contain the explicit local media scope.

- [ ] **Step 3: Implement the minimum governed adapter**

Implement only the three descriptors and their bounded JSON argument/result contracts. Wire a single MCPToolBoundary through Coordinator using its existing registry, permissions and StateStore. Register the OpenFilm capability as discovered without enabling or invoking it. Add the local permission scope only to the four specified role records. Add the read-only CLI status command. Do not add public HTTP endpoints, automatic lifecycle transitions or a worker scheduler.

- [ ] **Step 4: Verify the focused pass**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_openfilm_adapter.py' -v
python -m unittest discover -s tests -p 'test_mcp_boundary.py' -v
python -m unittest discover -s tests -p 'test_capabilities.py' -v
~~~
Expected: all three adapter tools are registered only for an enabled, verified fixture capability; unauthorized roles/scopes and unverified states are rejected before adapter dispatch; capability state is still discovered in the normal uneXpected configuration.

- [ ] **Step 5: Run the affected integration check**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_runtime.py' -v
python -m unittest discover -s tests -p 'test_command_center_api.py' -v
python -m unittest discover -s tests -p 'test_skills.py' -v
~~~
Expected: Coordinator lifecycle, existing HTTP routes, role registry and Skill loading remain unchanged except for the four explicit role scopes. No new public HTTP media route exists.

- [ ] **Step 6: Commit the passing deliverable**

~~~bash
git add unexpected_runtime/media/openfilm_adapter.py unexpected_runtime/coordinator.py agent_manifest.json unexpected_runtime/cli.py tests/test_mcp_boundary.py tests/test_openfilm_adapter.py tests/test_capabilities.py
git commit -m "feat(media): add governed OpenFilm MCP adapter"
~~~

---

### Task 3: Create the pinned OpenFilm Node runner

**Files:**
- Create: workers/openfilm/package.json
- Create: workers/openfilm/package-lock.json
- Create: workers/openfilm/run-job.mjs
- Create: workers/openfilm/test/run-job.test.mjs
- Create: workers/openfilm/UPSTREAM-NOTICES.md

**Interfaces:**
- Node runner contract: read one bounded JSON request from stdin and write one bounded JSON result to stdout. Diagnostics go to bounded stderr and contain no secrets or full source contents.
- The request identifies a validated job project root, a project-relative film entrypoint, a unique attempt output path and a declared render profile. The Python worker, not the job payload, supplies the fixed runner executable, working directory and permitted root paths.
- Import only OpenFilm's public look and render exports from the pinned openfilm package. Call look before render. If look reports errors, return a QA-blocked result and do not call render. On success, render only to the unique attempt-specific temporary output path.
- package.json pins openfilm exactly to 0.2.7 and declares Node >=22.18. package-lock.json contains the resolved tarball and integrity value. No floating version, Git branch dependency, npx @latest, arbitrary package execution or Studio/open CLI path is allowed.
- Verify the package's MIT license and include the upstream copyright/license notices in UPSTREAM-NOTICES.md. Record that the annotated upstream tag was unsigned and the resolved target commit is b7673b585e3e9c3b434fe663e68619cc1984ae8b.
- The runner must not read provider keys or make provider-generation requests. Browser/network containment is enforced by the host sandbox in Task 4, not by trusting project code.

- [ ] **Step 1: Add focused failing Node runner tests**

Test valid JSON request handling; malformed and oversized stdin; missing project entrypoint; look success followed by one render call; look errors preventing render; render failure returning a bounded failure; no path outside the supplied job root; no arbitrary command/CLI option accepted; no provider credential in the runner environment; and output JSON staying within the caller's byte ceiling.

- [ ] **Step 2: Verify the relevant failure**

Run:
~~~bash
cd workers/openfilm && node --test test/run-job.test.mjs
~~~
Expected: Node reports missing runner/test modules or the expected unimplemented contract failures; no OpenFilm package is installed on the command-center service.

- [ ] **Step 3: Implement the minimum pinned runner**

Create package metadata, generate the lockfile from the exact OpenFilm package version, verify package integrity and license text, and implement the narrow JSON runner around the public look/render exports. Reject malformed input and paths outside the supplied root. Never invoke the interactive Studio command or a shell.

- [ ] **Step 4: Verify the focused pass**

Run:
~~~bash
cd workers/openfilm && node --version && npm ci && npm ls openfilm && npm test
~~~
Expected: Node is v22.18 or newer; npm resolves openfilm@0.2.7 from the committed lockfile; all Node contract tests pass; npm does not report an unpinned OpenFilm dependency.

- [ ] **Step 5: Run the affected integration check**

Run:
~~~bash
cd workers/openfilm && npm audit --omit=dev
~~~
Expected: the dependency report is captured for review. Any unresolved high/critical dependency issue blocks worker installation; an audit result does not replace source, integrity and license review.

- [ ] **Step 6: Commit the passing deliverable**

~~~bash
git add workers/openfilm/package.json workers/openfilm/package-lock.json workers/openfilm/run-job.mjs workers/openfilm/test/run-job.test.mjs workers/openfilm/UPSTREAM-NOTICES.md
git commit -m "feat(media): pin OpenFilm Node render runner"
~~~

---

### Task 4: Build the one-job worker and fail-closed isolation boundary

**Files:**
- Create: unexpected_runtime/media/paths.py
- Create: unexpected_runtime/media/worker.py
- Create: unexpected_runtime/media/isolation.py
- Modify: unexpected_runtime/cli.py
- Create: tests/test_media_paths.py
- Create: tests/test_openfilm_worker.py
- Modify: .env.example
- Create: workers/openfilm/WORKER-SETUP.md

**Interfaces:**
- MediaWorker(job_service, isolation, config).run_once() claims at most one job, processes it, records the terminal or review state and exits. It does not loop, poll, schedule itself or launch another service.
- WorkerIsolation exposes self_test() and run_fixed_runner(request_bytes, project_root, attempt_root, limits, timeout_seconds). The default isolation implementation reports unavailable and refuses execution. A host-specific implementation may be added only after the local worker host is selected and its resource controls are verified.
- Worker configuration is mandatory and explicit: project root, artifact root, absolute Node path, absolute FFmpeg/FFprobe paths, wall-time ceiling, memory ceiling, CPU ceiling, project-byte ceiling, asset-count ceiling and output-byte ceiling. Missing or non-enforced limits make the worker unavailable; there are no permissive fallback defaults.
- paths.py resolves only relative paths under the configured project/artifact roots; rejects absolute paths, .. traversal, symlink escapes, device files, unsupported file types and hidden runtime/cache directories; and rechecks containment immediately before access/finalization.
- The worker runs as an unprivileged OS user or in a rootless sandbox; uses a fixed executable, fixed working directory and shell=False; constructs a minimal allowlisted environment; denies external network by default; and allows the film page to reach only its own project origin. It must block public internet, host metadata endpoints, unrelated loopback ports, host files and runtime/provider secrets.
- The process supervisor must terminate the complete child process tree, including Chromium and FFmpeg, on cancellation or timeout. It captures bounded stdout/stderr, enforces timeout and output size, and removes only that attempt's temporary files after confirming child processes have stopped.
- Each attempt gets a fresh temporary directory. Finalization uses an atomic no-overwrite operation. An existing destination is verified or causes the job to block; it is never silently replaced.
- The one-shot CLI command is python -m unexpected_runtime.cli media worker --once. It exits after one claim, or immediately with a no-job result. It does not run in the main uneXpected HTTP process or Render Free service.
- Rootless container isolation is the recommended initial engineering direction if the selected local host supports it; it is not assumed installed. A worker that cannot verify network, process and resource isolation remains disabled.

- [ ] **Step 1: Add focused failing isolation and worker tests**

Test path traversal, absolute paths, symlinks inside/outside root, device files, hidden runtime paths, oversized project, excess assets and oversized output. Test no-job exit; one job maximum; correct state progression; cancellation while rendering; timeout; subprocess non-zero exit; bounded stdout/stderr; child-process-tree termination; environment secret stripping; stale lease fencing; no-overwrite finalization; and fail-closed behavior when the isolation self-test or any configured limit is unavailable.

- [ ] **Step 2: Verify the relevant failure**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_media_paths.py' -v
python -m unittest discover -s tests -p 'test_openfilm_worker.py' -v
~~~
Expected: tests fail because the worker, path validator and isolation interface do not yet exist.

- [ ] **Step 3: Implement the bounded worker**

Implement path validation and the explicit configuration model. Implement the one-job claim/advance/cancel loop around the Task 3 runner. Add an unavailable-by-default isolation driver and a separately testable host driver only after a concrete host and its enforced quotas are selected. On a timeout, cancellation or worker crash, fence the lease and inspect the attempt/final paths before retry. Never assume a disconnected child stopped; never delete a directory while its child may still be writing.

- [ ] **Step 4: Verify the focused pass**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_media_paths.py' -v
python -m unittest discover -s tests -p 'test_openfilm_worker.py' -v
~~~
Expected: fake-isolation tests pass; absent host configuration returns unavailable without spawning Node; one configured fake job is processed at most once; cancellation and timeout leave no unverified artifact in a ready state.

- [ ] **Step 5: Run the affected integration check**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_media_jobs.py' -v
python -m unittest discover -s tests -p 'test_openfilm_adapter.py' -v
python -m unittest discover -s tests -p 'test_deployment_contract.py' -v
~~~
Expected: queue, adapter and worker contracts agree; the main Dockerfile and render.yaml still define one Python command-center web service and contain no Node/OpenFilm/FFmpeg/Chromium worker.

- [ ] **Step 6: Commit the passing deliverable**

~~~bash
git add unexpected_runtime/media/paths.py unexpected_runtime/media/worker.py unexpected_runtime/media/isolation.py unexpected_runtime/cli.py .env.example workers/openfilm/WORKER-SETUP.md tests/test_media_paths.py tests/test_openfilm_worker.py
git commit -m "feat(media): add isolated one-job worker"
~~~

---

### Task 5: Add technical post-render QA and artifact manifests

**Files:**
- Create: unexpected_runtime/media/qa.py
- Create: unexpected_runtime/media/manifest.py
- Create: tests/test_media_qa.py
- Create: tests/test_media_manifest.py
- Modify: tests/test_openfilm_worker.py

**Interfaces:**
- MediaQualityAssurance.run(project_root, output_path, variant, caption_paths, tools) returns a normalized report with per-check pass/fail, measured metadata, diagnostics and SHA-256 values.
- MediaManifest.build(job, project, outputs, qa_report) returns bounded JSON metadata containing campaign_id, content_id, platforms, title/description/CTA drafts, caption paths/languages, file sizes and hashes, rights/source notes, OpenFilm version, render settings, QA tool versions and QA outcome.
- FFprobe is invoked by a fixed absolute path and a fixed argument vector. Validate MP4 container, video stream, expected dimensions, frame rate, duration and audio-stream presence when audio_required is true.
- When audio is required, the job's QA profile must declare the integrated-loudness target and true-peak ceiling. Missing targets fail closed instead of inventing a platform standard. Verify source presence, audio coverage, silent gaps, integrated loudness and true peak against those declared values.
- FFmpeg black-frame and freeze-frame detection runs with explicit profile thresholds. Missing thresholds or tool failure make QA blocked. Generate a contact sheet/sampled frames for human inspection; automated frame sampling does not claim text understanding or visual approval.
- Validate SRT/VTT syntax, monotonic cue times, cue bounds within film duration, language metadata and synchronization tolerance when transcript timing is available.
- Hash the editable project inputs and each output. Verify the MP4 is present, non-empty and within the configured output-byte ceiling. A hash mismatch, missing file, invalid stream, wrong variant dimensions, missing required audio, out-of-profile loudness/peak, excessive black/freeze detection or malformed captions fails QA.
- A passing report advances only to ready_for_human_review. A defect advances to qa_blocked. No QA method calls Metricool or any external distribution service.

- [ ] **Step 1: Add focused failing QA and manifest tests**

Use deterministic fake ffprobe/ffmpeg JSON/text responses and tiny generated fixtures where available. Assert pass for a valid portrait MP4; fail for missing/zero-byte output, wrong width/height, missing video stream, wrong frame rate, excessive duration, missing required audio, incomplete audio coverage, loudness/true-peak breach, black/freeze threshold breach, missing caption, malformed SRT/VTT, non-monotonic timestamps, out-of-range cue, output-size breach and hash mismatch. Assert the manifest contains hashes and provenance but no absolute host paths or secrets.

- [ ] **Step 2: Verify the relevant failure**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_media_qa.py' -v
python -m unittest discover -s tests -p 'test_media_manifest.py' -v
~~~
Expected: focused tests fail because the QA and manifest modules are not present.

- [ ] **Step 3: Implement deterministic QA**

Implement fixed FFprobe/FFmpeg invocation, profile-driven thresholds, normalized result categories, contact-sheet generation, caption validation, file-size verification and SHA-256 read-back. Feed the report into MediaWorker's compare-and-set transition. Any missing required tool, profile field, output file or check result is a failure or qa_blocked state, never an implicit pass.

- [ ] **Step 4: Verify the focused pass**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_media_qa.py' -v
python -m unittest discover -s tests -p 'test_media_manifest.py' -v
~~~
Expected: every positive and negative fixture produces its asserted QA outcome; the manifest contains only bounded, non-secret metadata and content hashes.

- [ ] **Step 5: Run the affected integration check**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_openfilm_worker.py' -v
python -m unittest discover -s tests -p 'test_media_jobs.py' -v
~~~
Expected: QA pass leads to ready_for_human_review only; a defect leads to qa_blocked; neither path can produce published, uploaded or scheduled state.

- [ ] **Step 6: Commit the passing deliverable**

~~~bash
git add unexpected_runtime/media/qa.py unexpected_runtime/media/manifest.py tests/test_media_qa.py tests/test_media_manifest.py tests/test_openfilm_worker.py
git commit -m "feat(media): verify rendered artifacts and manifests"
~~~

---

### Task 6: Update the existing creative-media workflow and run the gated pilot

**Files:**
- Modify: skills/creative-media/WORKFLOW.md
- Modify: skill_manifest.json — recompute the creative-media SHA-256 after the workflow edit
- Modify: workflow_profiles/creative-media-studio.md
- Modify: CAPABILITY_MATRIX.md
- Modify: README.md
- Modify: CHANGELOG.md
- Modify: FILE_INVENTORY_SHA256.txt
- Create: examples/media/openfilm/maintenance-tracker-explainer/ — synthetic-data editable pilot project and local asset manifest
- Create: docs/operations/openfilm-local-worker.md
- Create: docs/qa/openfilm-pilot-review.md
- Modify: tests/test_skills.py
- Modify: tests/test_deployment_contract.py

**Interfaces:**
- The creative-media workflow invokes the existing roles only: orchestrator, creative-director, media-producer and voice-agent. No new specialist role is created.
- The workflow documents project brief → editable project → create job → status/cancel → one-shot worker → automated QA → human playback/listening → existing publishing handoff. It states that this integration is unavailable until capability and worker evidence gates pass.
- Update the creative-media Skill hash in skill_manifest.json and verify the runtime's hash-pinned Skill contract. Do not change manifest permissions beyond the four specified role scopes.
- The pilot uses original content, synthetic maintenance data and locally supplied/licensed assets only. It is tied to MAINTENANCE_TRACKER_GROWTH and one new YT-TRACKER-xx content ID; it does not edit or duplicate any approved/scheduled post.
- The pilot deliverables are the editable OpenFilm project, portrait YouTube Shorts MP4, portrait TikTok MP4, English captions, a French subtitle track only when timing is verified, QA manifest/checksums and human-review checklist. YouTube landscape 1920×1080 is produced only when requested by the pilot brief.
- Human review must open and play every exported MP4 end to end, listen to the complete soundtrack, and inspect transitions, captions, safe-area/CTA placement, sampled frames, black/frozen sections and final frame. Record the reviewer and result; automated QA alone cannot satisfy this gate.
- Publishing handoff contains files and metadata for the existing authorized Metricool workflow. It does not upload, schedule, publish, reply, DM, email or update customer accounts. Sales reporting records only evidence-backed enquiries, replies, demos and revenue.

- [ ] **Step 1: Add focused workflow and packaging tests**

Assert that the creative-media Skill describes OpenFilm's asynchronous flow, preserves existing approval gates, lists no arbitrary shell or provider-generation tool, has a matching SHA-256 manifest entry, introduces no new agent ID, does not claim external publication, and keeps the main deployment contract free of Node/Chromium/FFmpeg.

- [ ] **Step 2: Verify the relevant failure**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_skills.py' -v
python -m unittest discover -s tests -p 'test_deployment_contract.py' -v
~~~
Expected: the new assertions fail until the Skill, manifest hash and documentation are updated.

- [ ] **Step 3: Implement the workflow and pilot package**

Update the existing Skill and profile, recalculate the pinned Skill hash, amend capability/readme/changelog/inventory documentation, and add the synthetic pilot project plus its source/rights manifest. Document local worker setup, required isolation evidence, QA output and the manual Metricool handoff. Do not include actual customer data or real machine/employee/supplier records.

- [ ] **Step 4: Verify the focused pass**

Run:
~~~bash
python -m unittest discover -s tests -p 'test_skills.py' -v
python -m unittest discover -s tests -p 'test_deployment_contract.py' -v
python -m unexpected_runtime.cli media status
~~~
Expected: Skill hashes validate, the 38-role registry and one-service deployment contract are unchanged, and media status reports discovered/unavailable until a host passes its self-test.

- [ ] **Step 5: Run the full software and host acceptance checks**

Run:
~~~bash
python -m compileall -q unexpected_runtime
python -m unittest discover -s tests -v
cd workers/openfilm && npm ci && npm test
~~~
Expected: all available Python and Node unit/contract tests pass. PostgreSQL integration tests pass only when TEST_POSTGRES_DSN points to an isolated throwaway database; otherwise they remain explicitly skipped.

On the selected local worker host, separately run the worker isolation self-test, exact package-install verification, OpenFilm look/render smoke test, ffprobe/ffmpeg QA, cancellation/timeout recovery test and artifact hash read-back. Produce the pilot variants and complete the human end-to-end playback/listening checklist. This host test is not replaced by CI unit tests.

- [ ] **Step 6: Commit the passing deliverable**

~~~bash
git add skills/creative-media/WORKFLOW.md skill_manifest.json workflow_profiles/creative-media-studio.md CAPABILITY_MATRIX.md README.md CHANGELOG.md FILE_INVENTORY_SHA256.txt examples/media/openfilm/maintenance-tracker-explainer docs/operations/openfilm-local-worker.md docs/qa/openfilm-pilot-review.md tests/test_skills.py tests/test_deployment_contract.py
git commit -m "docs(media): integrate OpenFilm into creative workflow"
~~~

## Unresolved decisions required before host execution

1. **Worker host:** identify the persistent, resource-appropriate local machine that will run the one-shot worker. The existing Render Free service is excluded. The choice changes the isolation driver and what CPU, memory, process and network controls can actually be enforced.
2. **Artifact handoff:** decide how local project/MP4 files will be made available to the existing Metricool workflow at $0 recurring storage cost. A local path is not a public URL and cannot be assumed accessible from Metricool. Until this is resolved, the final handoff is manual and local.
3. **Enforceable resource limits:** after the host is selected, set and test CPU, memory, wall-time, maximum project bytes, asset count and output bytes against actual host controls. The worker stays unavailable when a configured limit cannot be enforced.
4. **Pilot QA profile:** approve the first pilot's integrated-loudness target, true-peak ceiling and black/freeze detection tolerances. These values must be explicit in the job profile; the implementation must not silently invent platform standards. Missing values block the corresponding required check.

Capability activation, deployment, Metricool upload/scheduling and public publishing remain separate approval gates even after the pilot passes.

## Execution handoff

The available execution path is inline, task-by-task implementation using the installed skillquiver executing-plans workflow. No subagent-driven implementation workflow is currently exposed in this host. This plan is saved for review; no runtime code, database migration, worker installation or deployment is included in this plan commit.
