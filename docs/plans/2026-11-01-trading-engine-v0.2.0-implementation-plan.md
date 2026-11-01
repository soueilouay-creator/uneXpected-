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
- Implement append-only SQLite paper account/fill journal, realized P&L and online backup/restore.

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
- Focused trading/API CI passed after these changes. Final full-suite results and release commit must be recorded before claiming completion.
