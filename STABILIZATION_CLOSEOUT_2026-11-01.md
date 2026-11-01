# uneXpected v7.3.1 — Stabilization Closeout

**Assessment date:** 2026-11-01  
**Release scope:** v7.3.1 only; no new roles, no architectural expansion, no major-version work.

## Verified source and automated checks

- Canonical repository: `soueilouay-creator/uneXpected-`.
- v7.3.1 implementation PR #2 is merged to `main` at `cdef6c263cbf44f0739a2b90070ec58059aca9a2`.
- Latest `main` documentation commit: `0a92f3571ffba01473813b4e4a39edc97e298be1`.
- GitHub Actions run #34 (`41290814628`) passed on that latest commit. Compile runtime, package integrity fixture, regression suite, and CLI smoke tests completed successfully.
- The run log reports 125 tests, 124 passed, one optional historical v6 archive fixture skipped, zero failures/errors.
- The deterministic-mock benchmark reports score 1.0, 8/8 critical checks, and 11/11 noncritical checks. It verifies runtime/control-plane contracts, not semantic quality of live model responses.

## Runtime test service

- Render service: `unexpected-v731-runtime-test` (`srv-dbj237m7bikc73e71pf0`).
- URL: `https://unexpected-v731-runtime-test.onrender.com`.
- Deployed source commit: `6b3ea2568b50e9e179f2a21f8f2aa7cc6d26d474`, whose application source tree matches the merged v7.3.1 implementation; the later `main` commit adds documentation/inventory updates only.
- Latest fresh health read: HTTP 200; service reports version 7.3.1, gateway provider configured, runtime authentication configured, privileged actions `fail-closed`.
- Fresh unauthenticated API probes returned HTTP 401. Render health is configuration presence, not proof of authenticated invocation or live provider success.
- The test service remains Free, public, auto-deploy disabled, and uses an ephemeral filesystem. It is not a production host and must not be used for durable approval/replay state or privileged operations.

## AI Studio and TAAFT status

- The separate `unexpected-ai-studio` Render service was not modified.
- Health returned HTTP 200 after an initial cold-start/503 response.
- Health metadata: `providerStatus: not verified`, no verified provider flags, `taaftEnabled: true`, `liveVerifiedToolCount: 28`, no listed warnings.
- TAAFT source/docs define 28 explicitly allowlisted public-catalog search/detail tools; read-only and no private TAAFT-account access. Configuration and count do not prove a live request.
- No live OpenAI, Anthropic, OpenRouter, or TAAFT model request was completed in this stabilization pass. No provider charge was initiated by the no-credential tests.
- Fresh unauthenticated POST probes to AI Studio `/test-provider` and `/orchestrate`, and runtime `/v1/invoke`, returned HTTP 401. No provider was reached.

## Security and governance

- Runtime HTTP API enforces bearer authentication; unauthenticated API access is rejected.
- Privileged runtime actions remain fail-closed.
- GitHub repository ruleset `CODEOWNERS review` (ID `26276986`) is still disabled. It does not presently enforce required independent code-owner review.
- The connected GitHub integration can read but cannot update rulesets; browser inspection was not authenticated. No policy change is claimed.
- Unit tests exercise approval validation and single-use replay through a fake GitHub transport. They are not a live approval/revocation/replay test against the host's real token, trusted reviewer list, or durable ledger.

## Remaining release gates

1. **Durable runtime state:** upgrade the existing Python test service to paid compute and attach persistent storage, or implement and test a managed transactional datastore migration. Current code expects SQLite; task state and approval replay ledger must survive restarts. The Render Free service cannot attach a persistent disk.
2. **Production identity/approval tests:** test positive approval, wrong reviewer, revoked/changed review, stale review, changed digest, and replay against the real GitHub integration after durable storage and trusted settings are configured. Keep privileged actions disabled until the full matrix passes.
3. **Repository protection:** enable appropriate required independent code-owner review and protected-main checks through GitHub settings; read back the active configuration.
4. **Live provider/TAAFT smoke:** securely verify the gateway token and perform an explicitly approved low-cost LIVE request. Preserve provider provenance. Do not treat configured secrets or TAAFT's enabled/count fields as successful calls.
5. **Backup/restore:** take a database-native backup, restore to an isolated target, and verify task state plus consumed-approval replay records survive.
6. **ChatGPT activation:** Library records can be stored separately, but Global Custom Instructions and ChatGPT Project activation need their own UI actions and read-back.

## Phone companion and storage boundary

The AI Studio repository contains a same-origin installable phone PWA at `/mobile/`. Its documentation describes on-device local projects, tasks, notes, chat history, and workspace backup/import. Offline caching covers the app shell and local workspace commands, not general LLM inference. The access token is not exported in workspace backups. The PWA does not grant this chat direct filesystem access or allocate a fixed 5 GB folder.

## Operating rule

Keep v7.3.1 scope frozen. Preserve mock as the default until live credentials and billing are confirmed. Do not enable privileged actions on the Free/ephemeral test host. Never put gateway, provider, GitHub approval, or runtime bearer tokens in chat, Git, PR comments, screenshots, or CI logs.
