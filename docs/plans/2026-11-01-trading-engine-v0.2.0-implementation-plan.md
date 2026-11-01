# Trading Engine v0.2.0 — Implementation Plan and Verification Record

## Sequence

### 1. Isolate and pin baseline
- Create `project/trading-engine-v0.2.0` from verified v0.1.0 commit `7efaa235f18d76c22e3b64489c9a94d2cc761bd8`.
- Leave main and v0.1.0 unchanged.
- Preserve upstream day-trader-skill MIT attribution.

### 2. Test-first contracts
- Add tests for typed source bars, synthetic fixture provenance, scanner, risk sizing, backtest reproducibility and partial-data rejection.
- Run the new CI test and observe the expected missing-package failure before implementation.
- Add SQLite reopen, idempotency, no-short, backup/restore, journal P&L, runtime authentication and live-field rejection tests.

### 3. Implement core engine
- Add validated Decimal data models.
- Add deterministic fixture and optional read-only Alpaca IEX adapter.
- Implement deterministic scanner and Decimal risk sizing.
- Implement reproducible breakout backtest with next-bar execution, friction and conservative stop-first tie policy.
- Implement append-only SQLite local paper account/fill journal, realized P&L and online backup/restore.
- Implement a managed Postgres backend with transactional fills and immutable ledger triggers; run integration tests against PostgreSQL 16 in CI.

### 4. Runtime integration
- Add typed API dispatch behind existing bearer-token auth and rate limiter.
- Add trading CLI subcommands.
- No Coordinator shell, generic Python tool, or broker order adapter.
- Keep journal writes fail-closed without explicit durable-storage flags.

### 5. Documentation and package integrity
- Update trading workflow skill to v0.2.0 and hash-pin it in the skill manifest.
- Update runtime docs, paper policy config, `.env.example`, README, deployment gate and structure/package tests.
- Add spec and plan.
- Refresh tracked-file SHA-256 inventory.

### 6. Final verification
- Compile runtime and engine.
- Build and validate repository ZIP fixture.
- Run complete `unittest discover -s tests -v` suite.
- Smoke CLI status/list/eval and trading health/scan/backtest.
- Read back branch head and changed files; ensure protected mainline has not moved.
- Do not merge or deploy without separate approval and host durability/configuration checks.

## Verification record

- Test-first CI red phase failed as expected with `ModuleNotFoundError: No module named 'trading_engine'`.
- Core engine tests passed after implementation.
- Runtime integration exposed SQLite cross-thread `ProgrammingError`; fixed by using one SQLite connection protected by a re-entrant lock.
- Runtime API tests then passed, including authenticated HTTP and rejection of live-mode fields.
- Journal P&L test was observed red because the journal did not yet expose realized P&L; the ledger was enhanced to label simulated fills and derive average-cost realized P&L including fees.
- The earlier SQLite-only release CI run #41308601652 passed (148 tests, one optional skip). A separate managed-Postgres migration is now being verified; its integration tests run against a PostgreSQL 16 service container.
- Final full regression result: 148 tests run, all passed, 1 existing optional legacy fixture skipped, 0 failures.
- Compile check passed for unexpected_runtime and trading_engine; the package-integrity ZIP was built and validated; CLI smoke checks passed for status, list, eval, trading health, synthetic scan and backtest.
- The branch head, changed source files, updated skill hash and 123-entry SHA-256 inventory were read back from GitHub. Protected main remains at 0a92f3571ffba01473813b4e4a39edc97e298be1; v0.1.0 remains at 7efaa235f18d76c22e3b64489c9a94d2cc761bd8.
- Hosted deployment remains blocked pending explicit approval of approximately $13.30/month for a Render Starter web service plus Basic-256mb Postgres with 1 GB storage, and setup of a permitted market-data credential. The existing Render Free smoke service remains untouched. Do not enable journal writes on any ephemeral service.


## Managed-host deployment preparation

The hosted database implementation is `trading_engine.postgres_portfolio.PostgresPaperPortfolio`. It is selected when `UNEXPECTED_TRADING_DATABASE_URL` or host-provided `DATABASE_URL` is present. Journal writes stay disabled unless `UNEXPECTED_TRADING_STORAGE_MODE=durable` and `UNEXPECTED_TRADING_ALLOW_JOURNAL_WRITES=true` are both set. CI supplies PostgreSQL 16 to verify schema creation, immutable-fill triggers, transactions, reconnect persistence, idempotency, long-only constraints and realized P&L.

Render production provisioning is separate from this source release. The workspace currently has no Postgres instance. Free Render Postgres expires after 30 days and has no managed backups; the minimum suitable persistent profile is paid. Await explicit user cost approval before creating the database and dedicated web service. Market-data credentials must be installed through Render's secret manager, not supplied in chat.
