# Creative Media Studio — Workflow Reference v1.1.0

This workflow is implemented by the existing uneXpected coordinator and canonical 38-role registry. It does not create a second coordinator, agent registry, database or public service.

## Native render route

- Preferred renderer: the native uneXpected OpenFilm capability (media.openfilm.render) through the existing CapabilityRegistry and MCPToolGateway.
- Use it only when the capability is enabled, the shared media-job store is ready, the adapter is registered, and the local worker preflight evidence is fresh and matches the current host configuration.
- One job contains exactly one platform variant. Create separate idempotent jobs for YouTube Shorts, TikTok or YouTube long-form outputs.
- Everygen is not a required dependency and must not be treated as the default renderer.
- If the native worker is unavailable, report the blocker. Do not silently fall back to a paid SaaS renderer.
- External video-generation providers are optional adapters only. Use one only when the user explicitly requests that route and the exact operation, cost/credits, rights and approval requirements have been checked.

## Asset preparation

- Use the existing creative roles to research, script, storyboard, create motion-graphic scenes, prepare captions and package assets.
- The native OpenFilm engine renders a supplied local project and its approved assets. It does not claim to generate realistic speech, music or original footage by itself.
- Voice, music and sound effects must be supplied, created by an available local tool, or generated through a separately approved optional provider adapter. Never invent asset rights or claim a provider ran without evidence.
- Keep project paths relative to the configured project root. Do not pass shell commands, arbitrary executable paths or secrets in render requests.

## Render and QA contract

- Pin the local worker image by immutable image ID. Require rootless Podman, cgroup v2, bounded CPU/memory/PIDs/tmpfs, a non-root worker, network denial, fixed Node/FFmpeg paths and one-job execution.
- Run FFprobe/FFmpeg QA against the actual MP4: container/streams, dimensions, frame rate, duration, audio coverage/loudness/true peak when required, black frames, freezes, caption syntax/timing and a contact sheet.
- Every render produces a portable artifact manifest with project/output hashes, renderer version, rights-manifest hash and QA results. Do not expose host paths or credentials in the manifest.
- Automated QA is not human playback. A human must watch and listen to the complete encoded master before it is marked human-reviewed.

## Publishing

- Uploading, scheduling, publishing, messaging, spending or changing connected accounts are separate actions.
- Never publish automatically from the render worker. Publish only the exact human-reviewed master after the separate platform workflow and required approval.
- Keep draft, rendered, QA-passed, human-reviewed, uploaded, scheduled and published as distinct states.
