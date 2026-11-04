# Local OpenFilm worker setup

This worker is an optional, one-job process belonging to the existing uneXpected installation. It is not a second command center, public service, database, scheduler or agent registry.

## Host requirements

- Linux host with rootless Podman and cgroup v2.
- A non-root user that can run Podman.
- Enough local CPU, memory and disk for the explicit job limits.
- FFmpeg and FFprobe on the host for post-render QA.
- The same uneXpected runtime state store as the coordinator. With SQLite, run the worker on the same host and state directory. With PostgreSQL, apply migration 004 to an isolated/tested database first and configure the same approved database connection in the worker environment.
- Do not use the current Render Free service as the renderer host.

## Build and pin the local worker image

From `workers/openfilm`:

```bash
podman build -f Containerfile -t localhost/uneXpected-openfilm-worker:0.2.7 .
podman image inspect --format '{{.Id}}' localhost/uneXpected-openfilm-worker:0.2.7
```

Copy the returned immutable `sha256:<64 lowercase hex>` image ID into the host's private environment as `UNEXPECTED_OPENFILM_WORKER_IMAGE`. Do not use a floating image tag in the runtime setting. The runtime does not pull or install an image automatically.

## Configure the worker

Set every required `UNEXPECTED_OPENFILM_*` value from `.env.example` in the host's secret/configuration manager. Paths must be absolute. Choose explicit host ceilings and lower per-job limits. The job timeout must be at least ten seconds shorter than the lease. The worker does not receive model-provider keys and its container has no network.

For a local SQLite deployment, keep the coordinator and one-shot worker on the same machine and point both at the same `UNEXPECTED_STATE_DIR`. For PostgreSQL, use the already-configured shared state store only after the additive migration and recovery tests pass. Never put credentials in project files or commit them.

## Lifecycle

1. Inspect `python -m unexpected_runtime.cli media status`.
2. Review the pinned source and local build; record a reviewer with `media review --reviewer ... --reason ...`.
3. Mark the locally built worker package installed with `media install --reason ...`.
4. Run `python -m unexpected_runtime.cli media preflight`. It must prove rootless Podman, cgroup v2 resource limits, the exact local image ID, non-root execution, FFmpeg/FFprobe availability and denied network access.
5. Only after preflight passes, explicitly enable the capability with `media enable --reason ...`.
6. Queue a job with `media enqueue --request-json '<JSON>'`.
7. Run exactly one job with `python -m unexpected_runtime.cli media worker --once`. The process exits after one claim or an idle result; it does not poll or schedule itself.
8. Review the generated MP4, contact sheet and manifest. Human playback/listening is required before any separate publishing approval.

A missing setting, failed host probe, unsupported resource limit, missing FFmpeg tool or failed QA blocks rendering. No external generation provider, upload, schedule or public post is triggered by this worker.
