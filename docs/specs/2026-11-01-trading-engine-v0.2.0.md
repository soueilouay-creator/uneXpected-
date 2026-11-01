# Trading Engine v0.2.0 — Design Specification

**Status:** Implemented and full-suite CI verified on isolated branch; hosted deployment remains separately gated.  
**Base:** uneXpected v7.3.1 / Trading Intelligence v0.1.0  
**Target branch:** `project/trading-engine-v0.2.0`  
**Market scope:** US-listed common stocks and ETFs, long-only, paper-only.

## Goals

Provide an executable trading-research engine behind uneXpected's typed API and CLI while keeping arbitrary Python execution out of the Coordinator. Support controlled market data, deterministic scans, explicit risk calculations, reproducible backtesting and a persistent paper journal.

## Architecture

- `trading_engine.models`: validated Decimal OHLCV bars, strict symbols and timezone-aware timestamps, source/feed/timeframe/status provenance.
- `trading_engine.data`: `MarketDataProvider` protocol, synthetic deterministic fixture source, and optional read-only Alpaca market-data adapter.
- `trading_engine.scanner`: 20-bar breakout, 20-bar SMA reclaim, RSI-14 oversold bounce and 15-minute opening-range signal.
- `trading_engine.risk`: Decimal long-only whole-share sizing under risk budget, cash, position percentage and remaining daily-loss caps.
- `trading_engine.backtest`: long-only breakout simulation with next-bar-open entry, explicit commission/slippage, stop-first intrabar collision, metrics and data/config hashes.
- `trading_engine.portfolio`: append-only SQLite simulated-fill journal for local runs, idempotency, derived cash/positions, average-cost realized P&L, integrity checks and SQLite online backup.
- `trading_engine.postgres_portfolio`: managed PostgreSQL backend with schema-scoped migrations, database transactions, account-row locking, idempotent simulated fills, immutable journal triggers, derived average-cost realized P&L and database connectivity/schema checks.
- `trading_engine.service`: typed service boundary with fixture default, optional provider selection and fail-closed journal writes.
- `unexpected_runtime.trading_api`: authenticated strict-schema HTTP integration; the existing Coordinator remains the model orchestration runtime, not a code execution sandbox.

## Data-source controls

Fixture bars are synthetic and must be labelled as such. Optional Alpaca access is hard-coded to `https://data.alpaca.markets`, requests GET-only stock bar data, forces the IEX feed, rejects redirects, uses bounded timeout and response size, and requires host environment secrets. It does not retry non-idempotent operations, access trading/order endpoints or expose arbitrary URL input. A provider page token marks a result partial; backtests reject partial input.

IEX is a single-exchange feed and must not be described as consolidated SIP. The provider may be rate limited or historical data delayed; source and retrieval timestamps must be distinguished.

## Risk controls

All monetary arithmetic uses Decimal. Invalid/non-finite or nonpositive values fail. Long stop must be below entry; target must be above. Quantity is the minimum of the risk-limited, position-limited and cash-limited whole-share values. Optional daily-loss ceiling reduces remaining risk to zero at the limit. No default personal equity, max loss, max daily loss or max position percentage is inferred.

## Backtest semantics

A signal is computed after a completed bar close. Entry is at the following bar open plus configured slippage. Exit rules are stop and target, with stop-first treatment if both are touched in the same bar. Commissions and slippage are modelled. Dataset and config fingerprints are SHA-256. Results include net return, maximum drawdown, win rate, profit factor, trades, wins/losses and bar context. The implementation is a simple deterministic long-only breakout baseline, not an optimized strategy library. Survivorship bias, market impact, taxes, corporate-action subtleties and missing intraday detail remain limitations.

## Paper journal and storage

SQLite maintains a local paper account and immutable simulated-fill rows. Managed Postgres provides the hosted implementation: schema-scoped creation, account-row locking during fills, database constraints and triggers that reject updates/deletes, and reconnect-persistence checks. Both backends derive cash, positions, average cost and realized P&L from the immutable fill history.

Render paid Postgres provides managed point-in-time recovery; on the Hobby workspace its current documented recovery window is three days, and logical exports are retained for seven days. CI runs integration tests against a PostgreSQL 16 service container. This verifies SQL behavior, not the persistence of a production Render database.

API journal writes fail closed unless both `UNEXPECTED_TRADING_STORAGE_MODE=durable` and `UNEXPECTED_TRADING_ALLOW_JOURNAL_WRITES=true` are explicitly set by the operator. The service selects managed Postgres through `UNEXPECTED_TRADING_DATABASE_URL` (or host-provided `DATABASE_URL`) and reports the active backend in health. Storage-mode flags do not themselves prove durability; the operator must verify the managed database, test a service restart and confirm the provider's recovery workflow.

## Runtime routes

- `GET /v1/trading/health`
- `POST /v1/trading/scan`
- `POST /v1/trading/risk-check`
- `POST /v1/trading/backtest`
- `POST /v1/trading/accounts`
- `POST /v1/trading/paper-orders`
- `GET /v1/trading/portfolio?account_id=...`
- `GET /v1/trading/journal?account_id=...`

All routes require the existing runtime bearer token, use the request rate limiter and strict field allowlists. Request bodies are bounded. No `live`, `trade`, generic execution, broker action or scheduler API is provided. CLI equivalents are documented in `trading/README.md`.

## Exclusions

No live brokerage, real orders, short selling, margin, leverage, options, crypto, scheduled polling, background alerting, portfolio sync or automated buy/sell advice. No paid market-data plan is required for the initial IEX feed. A paid persistent host/database is not provisioned by this source release and requires explicit user approval. No default risk values.

## Acceptance criteria

1. Validated bars and clear synthetic/source/feed provenance.
2. Fixture provider works offline; unconfigured Alpaca fails closed without network.
3. Scanner outputs deterministic signals and source provenance; partial scans are reported.
4. Risk sizing rejects invalid long structure and caps quantity by risk, cash, position and daily-loss settings.
5. Backtest refuses partial data, rejects implicit initial capital and yields stable dataset/config hashes and metrics.
6. Paper ledger persists across connection reopen, is idempotent, forbids short sales, calculates realized P&L, labels fills and passes backup/restore integrity.
7. Threaded runtime API serves authenticated endpoints; unauthorized access denied; live-mode fields rejected; paper writes disabled when storage is not durable.
8. Full repository regression suite, compile checks, package integrity, engine tests and CLI smoke commands pass on this branch.
9. Mainline remains unchanged; no deploy/merge performed.
