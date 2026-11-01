# uneXpected Trading Intelligence v0.2.0

This isolated project branch adds a native paper-trading engine behind uneXpected's typed runtime API and CLI. The workflow adapts the capability structure of `Jakeschincariol/day-trader-skill` v2.0.0, upstream commit `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`, under the MIT license. See `UPSTREAM_NOTICES/LICENSE` and `UPSTREAM_NOTICES/SOURCE_MANIFEST.json`.

## Implemented capabilities

- Synthetic fixture provider for deterministic offline tests; fixture prices are never described as actual market data.
- Optional read-only Alpaca Market Data adapter using a fixed host and IEX feed. It requires host-configured API keys; no keys are stored in the repository or sent to the model. IEX is not consolidated SIP data.
- Deterministic completed-bar scans: 20-bar breakout, 20-bar SMA reclaim, RSI-14 bounce, and 15-minute opening-range rule.
- Decimal-based long-only risk sizing with explicit inputs for equity, cash, stop, target, risk budget, position cap and optional daily-loss cap.
- Reproducible breakout backtests with dataset/config SHA-256 fingerprints, next-bar-open entry, commission/slippage, conservative stop-first intrabar tie handling and documented limitations.
- SQLite paper account for local use and managed PostgreSQL ledger for hosted use. Both provide append-only simulated fills, idempotency keys, cash/position derivation and realized average-cost P&L including fees. PostgreSQL is integration-tested against PostgreSQL 16 in CI. Paid Render Postgres supplies managed point-in-time recovery.
- Authenticated typed runtime endpoints and local CLI commands. The Coordinator does not expose arbitrary Python execution.

## Safety and operating boundaries

The engine is strictly `PAPER_ONLY`. There is no live or paper broker connector; the paper functionality is a local simulated ledger with no broker link. There is no live order endpoint and no ability to place, modify, cancel or close a real order. No options, crypto, margin, leverage, short selling, background polling or unattended alerts are enabled.

The upstream Python executables are inventoried by Git blob SHA but are **not copied, installed, executed or exposed as tools**. This is not a Python execution engine for those upstream scripts; the native engine here is a separately implemented package.

Paper journal writes are disabled by default. The API returns a fail-closed error until an operator has configured an approved durable database URL and explicitly set both storage flags. For hosted Render use managed PostgreSQL through `UNEXPECTED_TRADING_DATABASE_URL`. Render Free web-service storage is ephemeral and Free Postgres expires after 30 days without managed backups; neither is suitable as a permanent paper journal. A CI Postgres container verifies database behavior but is not production persistence.

## Quick start

From the repository root on branch `project/trading-engine-v0.2.0` with Python 3.12:

```bash
python -m unexpected_runtime.cli trading health
python -m unexpected_runtime.cli trading scan --symbols DEMO
python -m unexpected_runtime.cli trading risk-check --payload '{"symbol":"DEMO","equity_usd":"10000","cash_available_usd":"10000","entry_price":"100","stop_price":"95","target_price":"110","max_loss_usd":"100","max_position_pct":"20"}'
python -m unexpected_runtime.cli trading backtest DEMO --initial-cash 10000
```

The default provider is synthetic `fixture`. The Alpaca option is enabled only after configuring `UNEXPECTED_TRADING_DATA_PROVIDER=alpaca`, `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in the host secret manager. The adapter only issues GET requests to `data.alpaca.markets` for IEX stock bars and never calls the trading API host. Prefer paper-account keys if using the standard Trading API key pair; the runtime has no broker order route. Alpaca Basic currently offers US stocks/ETFs on IEX, 200 historical API calls per minute and a latest-15-minute historical data limitation; it is not consolidated SIP data.

## Runtime API

Set `UNEXPECTED_RUNTIME_API_TOKEN` to a random secret of at least 32 ASCII characters in the host environment. Start with:

```bash
python -m unexpected_runtime.http_api
```

Authenticated endpoints:

- `GET /v1/trading/health`
- `POST /v1/trading/scan`
- `POST /v1/trading/risk-check`
- `POST /v1/trading/backtest`
- `POST /v1/trading/accounts`
- `POST /v1/trading/paper-orders`
- `GET /v1/trading/portfolio?account_id=...`
- `GET /v1/trading/journal?account_id=...`

Use `Authorization: Bearer <token>`. The request schemas are strict, request bodies are bounded, and the runtime rate-limits requests. `paper-orders` records simulated fills only; unsupported fields such as `mode=live` are rejected. Journal writes are still off unless durable storage is explicitly enabled.

## Verification

`python -m unittest discover -s tests -v` runs the repository test suite. GitHub Actions on this branch runs compile checks, package integrity, trading-engine tests, runtime tests and CLI smoke tests. No production deployment, real provider request or live broker connection is implied by CI success.
