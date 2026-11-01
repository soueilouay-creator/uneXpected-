# Trading Operations Workflow Profile v0.2.0

**Type:** Workflow profile; not a new canonical agent.
**Skill:** `trading-ops@0.2.0`
**Mapped roles:** `orchestrator`, `investment-research`, `data-analyst`.
**Escalation:** `security-reviewer` for data, connector and secret boundaries; `legal-scout` for jurisdiction or source-terms questions.

## Routing

- Market scans, chart setups, entries, exits and earnings: `investment-research` with `data-analyst` for calculations.
- Position sizing, risk and paper journal arithmetic: `data-analyst`, reviewed by `investment-research`.
- Multi-step research and final synthesis: `orchestrator`.
- No new role IDs are introduced. No broker, scheduler, external-write or privileged tool is assumed.

## Permission boundary

The workflow consumes verified data and returns research or paper-only artifacts. It cannot authorize or invoke `trade`, `external_write`, broker actions, background scheduling, credential access or deployment. Existing host permission enforcement remains authoritative and fail-closed.

## Runtime integration

The `trading_engine` package exposes synthetic fixture scanning, optional read-only IEX market data, explicit-input risk sizing, reproducible historical simulation, and an append-only SQLite paper-fill journal with realized P&L. Runtime routes are authenticated and typed. Journal writes remain disabled unless durable storage is explicitly configured. There is no broker order endpoint, live trading, unattended monitoring or arbitrary code execution.

## Acceptance checks

1. Hash-pinned workflow resolves only to the mapped existing roles.
2. Trading phrases attach the workflow; unrelated maintenance, creative and sales tasks do not.
3. Context explicitly states paper-only operation and no live broker execution.
4. Missing/stale market data and absent personal risk inputs are reported, not invented.
5. This profile adds no canonical agents or external permissions.
