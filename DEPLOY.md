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

## Trading engine v0.2.0 — deployment gate

This engine is available on the isolated branch `project/trading-engine-v0.2.0`; the v7.3.1 mainline and current Render test service have not been changed by it.

- Keep `UNEXPECTED_TRADING_DATA_PROVIDER=fixture` until permitted market-data credentials have been installed in the host secret manager.
- For Alpaca, store `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` only in the host secret manager. The adapter uses a fixed `data.alpaca.markets` host, the IEX feed, and GET-only stock-bars requests. It never calls a broker/trading endpoint. Prefer paper-account keys for standard Trading API credentials; the code has no broker order route.
- Set `UNEXPECTED_TRADING_DATABASE_URL` to the managed Postgres internal connection URL in the host secret manager. The engine creates an isolated `unexpected_trading` schema and applies idempotent DDL at startup.
- Keep `UNEXPECTED_TRADING_STORAGE_MODE=ephemeral` and `UNEXPECTED_TRADING_ALLOW_JOURNAL_WRITES=false` until the database is confirmed healthy, survives a service restart/redeploy, and a recovery path has been verified. Only then set `UNEXPECTED_TRADING_STORAGE_MODE=durable` and `UNEXPECTED_TRADING_ALLOW_JOURNAL_WRITES=true`. Health checks validate DB connectivity/schema access but cannot prove the provider's full recovery point.
- Keep `UNEXPECTED_RUNTIME_API_TOKEN` random and at least 32 ASCII characters, stored only in the host secret manager. Use TLS termination and restrict who can reach the service.
- The runtime health endpoint reports configured storage mode and database integrity but cannot independently prove that a host volume survives redeploy or restart. Perform an actual persistence and restore drill before enabling writes.

There is no broker, live-order, scheduled polling or unattended trading function in v0.2.0. No production deployment is claimed by this source branch or its GitHub Actions tests.


### Render managed PostgreSQL deployment profile

The release supports a separate Render web service plus managed Postgres in Frankfurt. The minimal persistent profile currently estimates:

- Web service: Starter / sub-1-CPU plan, approximately $7/month.
- Postgres: Basic-256mb, approximately $6/month, plus minimum 1 GB storage at $0.30/month.
- Estimated baseline: approximately $13.30/month before taxes, bandwidth and usage. Verify the current quote at provisioning.
- Paid Render Postgres provides point-in-time recovery. On the Hobby workspace the documented recovery window is three days; logical exports are retained for seven days.
- Do not create either paid resource without explicit user approval of recurring cost.
- Free Render Postgres expires after 30 days and does not provide managed backups; it is not acceptable as the permanent paper journal.

The current workspace has no Postgres instance. Do not change or reuse the existing v7.3.1 Render test service. Create a new service on branch `project/trading-engine-v0.2.0` and keep all broker/live-order capabilities absent.
