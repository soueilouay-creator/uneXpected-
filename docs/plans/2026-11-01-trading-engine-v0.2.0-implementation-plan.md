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
- Final branch CI run #41308601652 completed successfully on GitHub Actions with Python 3.12 at source commit 1a977a0d21218a407619aefab41bedcba82ac893.
- Final full regression result: 148 tests run, all passed, 1 existing optional legacy fixture skipped, 0 failures.
- Compile check passed for unexpected_runtime and trading_engine; the package-integrity ZIP was built and validated; CLI smoke checks passed for status, list, eval, trading health, synthetic scan and backtest.
- The branch head, changed source files, updated skill hash and 123-entry SHA-256 inventory were read back from GitHub. Protected main remains at 0a92f3571ffba01473813b4e4a39edc97e298be1; v0.1.0 remains at 7efaa235f18d76c22e3b64489c9a94d2cc761bd8.
- Host deployment was not performed. The existing Render Free smoke service is pinned to integration/v7.3.1-governed-runtime, has auto-deploy disabled and an ephemeral filesystem; changing it or creating a new public service would be a separate deployment decision. Journal writes must remain disabled there.
