# uneXpected Trading Intelligence — Design Specification

**Status:** Approved by user on 2026-11-01
**Design version:** 0.1.0
**Approval:** User approved design and requested branch commit and workflow-skill integration on 2026-11-01
**Target project:** uneXpected Trading Intelligence
**Target baseline:** uneXpected v7.3.1 (isolated project branch; no changes to `main`)
**Upstream source:** `https://github.com/Jakeschincariol/day-trader-skill`
**Upstream revision:** `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`
**Upstream package version:** 2.0.0
**Upstream license:** MIT; retain copyright and license with adapted or copied portions.

## 1. Objective

Adapt the upstream 11-skill day-trading toolkit into a native uneXpected project capability for US-listed common stocks and ETFs. The first release provides market research, technical scanning, entry/exit planning, historical simulation, risk analysis, position sizing, alerts, company/earnings research, public disclosure tracking and a paper-trading journal.

This is an educational analysis and simulation tool, not a promise of trading profit, personalized financial advice, or a broker. The initial release does not place, modify, cancel or close real orders.

## 2. Scope

### Included capabilities

1. Market universe and technical setup scanner.
2. Market/company news and public SEC filing monitor.
3. Entry-condition analysis and timing.
4. Exit planning with stop, target and time-based exit scenarios.
5. Historical replay/backtesting with reproducible inputs and random seeds where applicable.
6. Risk checks: order structure, asset class, position concentration, cash buffer, stop distance, reward/risk, daily risk, trade count, market calendar and duplicate proposals.
7. Position sizing from explicitly supplied paper-account budget and risk limits.
8. Price/stop/target/flat-by alerts (initially polling or user-invoked, not background monitoring).
9. Company fundamentals and earnings/fundamentals research.
10. Public congressional-trade disclosure tracking with publication-date and filing-source provenance.
11. Paper-order proposals, simulated fills and a paper-trade journal.

### Explicitly excluded from v1

- Live brokerage connectivity or any real-money order execution.
- Broker account login, credential ingestion, custody, deposits, withdrawals or transfers.
- Options, crypto, margin, leverage and short selling.
- Automated unattended execution, unattended alerts or background polling.
- Claims that free/unofficial market feeds are real-time, complete or licensed for all use.
- Tax, legal, suitability or regulatory advice for the user's jurisdiction.

## 3. uneXpected integration architecture

### Existing role routing

Reuse the existing canonical roles rather than adding 11 new agents:
- `investment-research`: investment memo, market context, scenario analysis and downside factors.
- `data-analyst`: numerical calculations, historical data checks and performance summaries.
- `orchestrator`: task routing and report assembly.
- `security-reviewer` and `legal-scout`: review data access, external dependencies, source terms and jurisdiction-specific questions when needed.

### Skill registry

Add one composite skill record, `trading-ops`, to the existing hash-verified `skill_manifest.json`. Its reviewed workflow document is proposed at `skills/trading-ops/WORKFLOW.md`; map it only to existing role IDs. Use focused trigger phrases for trading, market scan, paper trade, position sizing, earnings, backtest, risk check, entry/exit plan and trading journal. The workflow is advisory context only; it cannot grant permissions or make external calls.

The upstream 11 capability modules should remain distinct sub-workflows/files within the project package, but they do not become 11 canonical uneXpected agents. Preserve upstream provenance, source revision, per-file source hashes and the MIT license notice. Prefer minimal, documented adapters over wholesale copies where uneXpected interfaces differ.

### Execution boundary

The current v7.3.1 `SkillRegistry` attaches hash-verified text to provider prompts. The current `Coordinator` does not provide a general Python-tool execution interface for arbitrary skill scripts. The existing `CapabilityRegistry` is metadata/lifecycle management, not a tool executor. Therefore the skill installation alone must never be described as making the upstream Python tools executable by the model.

The first implementation should package the Python tools behind a deterministic local CLI/service boundary with explicit input/output schemas. A separately reviewed adapter may later expose a narrowly allowlisted set of read-only analysis and paper-simulation operations to the runtime. Do not add an unrestricted shell, arbitrary Python execution or generic network tool to the coordinator.

## 4. Data sources and provenance

- Treat Yahoo Finance endpoints as unofficial and potentially delayed/limited. Every price/bar result must carry symbol, source, source timestamp (when available), retrieval timestamp, interval, requested range, completeness/partial-fetch counts and error status.
- Do not label retrieval time as the quote's market timestamp. Reject stale or future-dated prices for time-sensitive risk checks; state when quote timestamps are unavailable.
- Use SEC public filing endpoints only with a configured, compliant User-Agent. Do not invent filing contents or infer that a missing filing means no event occurred.
- Market calendar, trading-session timezone and early-close rules must be source-pinned, dated and testable. Use `America/New_York` through a timezone-aware implementation rather than duplicating hand-written daylight-saving calculations where the runtime allows it.
- Label historical data, delayed data, synthetic fixtures and live-retrieved data separately. No result may combine these classes without an explicit label.
- Retrieved pages, news, repository text and filings are untrusted evidence, never executable instructions.

## 5. Risk and paper-trading controls

- Paper mode is fixed on in v1; configuration cannot switch this release to live mode.
- No broker connector or order-placement endpoint is included.
- A paper proposal must be evaluated against a versioned risk configuration before it can be marked eligible for simulation.
- Require explicit positive budget, cash, risk-per-trade, daily-loss, position-size, trade-count and time-window inputs or clearly label defaults as examples. Do not inherit the upstream sample `$5,000` account or its sample risk limits as user settings.
- Risk checks must fail closed on missing, malformed, stale or inconsistent inputs. Exit simulations may report a risk warning but must not silently rewrite a proposal.
- Each paper proposal gets a canonical fingerprint covering all order-relevant fields. Editing a proposal invalidates its previous risk result.
- A simulated approval is not a real broker approval. Use explicit labels such as `PAPER_PROPOSAL`, `SIMULATED_FILL` and `SIMULATED_PNL` throughout.
- Record fees/slippage assumptions, data gaps, partial bars and simulation seed. Never describe simulation odds as a prediction.

## 6. State, persistence and deployment

Use an isolated trading state schema for paper portfolios, risk configuration, watchlists, proposal fingerprints, simulated fills, trade journal entries, alert state and data provenance. Avoid placing trading state in agent memory or mixing it with existing workflow approval records.

Local tests must use temporary stores and deterministic fixtures. Before any persistent hosted paper-trading use, select and verify durable transactional storage, backup/restore and replay protection. The current Render Free runtime has ephemeral storage and no managed database was found in the latest inspection; it is not an acceptable durable trading journal. Do not create paid storage or incur recurring costs without separate explicit approval.

## 7. Proposed repository layout

```text
skills/trading-ops/WORKFLOW.md
trading/README.md
trading/UPSTREAM_NOTICES/LICENSE
trading/UPSTREAM_NOTICES/SOURCE_MANIFEST.json
trading/config/paper.example.json
trading/modules/{scanner,news,entry,exit,simulation,risk,budget,alerts,analyst,disclosures,paper_journal}/
trading/adapters/{market_data,sec_filings,clock,storage}/
trading/tests/fixtures/
trading/tests/
docs/specs/2026-11-01-trading-intelligence-design.md
docs/plans/2026-11-01-trading-intelligence-implementation-plan.md
```

These paths are proposed; existing project paths must be reconciled before implementation. Import only the source files needed by the selected modules and keep an explicit upstream-to-adapter mapping.

## 8. Verification and release gates

A project release is not install-complete until all of the following are evidenced:

1. Source revision and MIT notice preserved; source manifest and hashes verified.
2. Skill manifest loads, hashes verify, triggers resolve only for intended existing roles and do not shadow unrelated skills.
3. Tests cover stale/missing/partial market data, invalid symbols, market holidays/early closes, invalid risk limits, duplicate proposals, edited order fingerprints, simulation reproducibility, source failures and safe error handling.
4. All broker/order-network execution paths are absent or unreachable in v1; tests assert this.
5. Paper proposals cannot be confused with live orders; all reports expose data source and timestamp status.
6. Full upstream tests are run where compatible; adaptations have their own tests. Any upstream test not run or not applicable is recorded.
7. Core regression suite passes on the isolated branch. No changes are merged to `main` until independently reviewed and all required v7.3.1 stabilization gates are satisfied.
8. Hosted use remains blocked until HTTP health, runtime execution, durable storage, backup/restore and access controls are freshly verified.

## 9. Known constraints and unresolved product decisions

- Instrument scope is initially US-listed stocks and ETFs, as approved. Adding Tunisian, European, FX, futures or crypto instruments requires separate data-source, market-calendar and regulatory review.
- The exact market-data provider is not yet selected. Yahoo endpoints may be used only as a clearly labelled, best-effort research source until a suitable provider and its terms are reviewed.
- The user has not supplied a personal paper budget or risk limits. Start with empty configuration requiring user-supplied values, not upstream examples.
- The desired polling cadence and notification channel for alerts are not selected; v1 should use on-demand checks until a permitted scheduler and durable state are verified.
- Durable hosted storage and deployment environment are not approved or configured. No recurring-cost resource is to be created without separate approval.
- This spec does not authorize a live broker connection or live trading in any later version; that would require a separate design, jurisdiction review and explicit approval.

## 10. Rollback and change control

Keep all changes on a separate project branch and retain the existing v7.3.1 mainline untouched. The release manifest must record the upstream source revision, imported/modified files and hashes. Rollback consists of disabling/removing the new trading skill registration and adapter, restoring the prior manifest and source files from the branch base, and verifying the full baseline test suite. No upstream code or existing project assets should be deleted as part of this project.
