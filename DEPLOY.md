# Deploy / Host uneXpected v7.3.1

The package is a local CLI/runtime scaffold. A production service requires a separately authorized host, persistent storage and deployment process.

1. Choose a host and isolation model; use a dedicated least-privilege account/container.
2. Pin Python, the package checksum and source-control revision.
3. Keep secrets in the host secret manager. Begin with the deterministic mock provider and no external-action scopes.
4. Provide persistent storage for SQLite state, backups, disk limits, log retention, supervision and health checks.
5. Implement each external tool as a narrow adapter with documented scopes, approval and abuse tests.
6. Run full unit tests, live-provider smoke tests, backup/restore drills and timeout/cost tests.
7. Record host, revision, test evidence, owner, rollback command and monitoring before claiming deployment.

No production deployment was performed by the original build.

## GitHub-backed privileged-action approvals

The GitHub verifier checks a committed request at the exact open PR head, an approval by a trusted admin on that head, current permission, expiry and a one-use SQLite ledger. Configure `UNEXPECTED_GITHUB_APPROVAL_ALLOWED_REPOSITORIES` as an exact comma-separated owner/repository allowlist; the configured target must be a member or the verifier remains disabled. It fails closed on API or ledger errors. It requires a distinct requester and approver. Keep it disabled until an independent reviewer, a protected base branch, a host-held read-only token and persistent storage are available. The current ledger is local to one instance; do not horizontally scale it.

## Real AI gateway and bounded runtime API

See docs/RUNTIME_CONNECTIVITY.md for connection to the existing AI Studio OpenAI/Anthropic/OpenRouter gateway, secure token handoff, provider modes and the unprivileged HTTP API. In `ai_studio_gateway` mode, the Python runtime receives only the separate gateway bearer token and provider keys stay in the Node gateway. The optional `openai_compatible` mode instead reads `UNEXPECTED_API_KEY` in the Python host environment. The runtime API does not accept approval claims or privileged permission fields. Keep mock mode as default until the host secret settings and a live request have been verified.


## v7.3.1 stabilization test host — 2026-11-01

A separate Render Free web service named `unexpected-v731-runtime-test` is deployed from `soueilouay-creator/uneXpected-`, branch `integration/v7.3.1-governed-runtime`, at tested source commit `6b3ea2568b50e9e179f2a21f8f2aa7cc6d26d474`. The build command compiles the Python runtime and tests; GitHub Actions run #32/#33, not Render, executed the full regression suite. The health endpoint returned HTTP 200 and the unauthenticated `/v1/status` and `/v1/invoke` routes returned 401.

This host is a smoke-test environment only: Free plan, ephemeral filesystem, no persistent approval ledger, and auto-deploy disabled. It is not the production deployment and must not be used to enable privileged actions. Its health response reports gateway/API credentials configured, but no authenticated invoke or live model response was verified.

The `CODEOWNERS review` repository ruleset remains disabled and must be enabled separately. Live provider/TAAFT verification, persistent storage, approval replay/revocation tests and production backup/restore remain production gates.
