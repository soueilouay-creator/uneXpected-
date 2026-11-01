# uneXpected Trading Intelligence Implementation Plan

> **For agentic workers:** Use the host's available task-by-task implementation workflow. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provenance-pinned paper-only trading research workflow to uneXpected v7.3.1 on an isolated project branch without altering mainline or granting external permissions.

**Architecture:** Register one hash-verified composite workflow in the existing `SkillRegistry`, mapped to existing roles `orchestrator`, `investment-research` and `data-analyst`. Store paper-only policy metadata and upstream license/source inventory separately. The runtime will attach Markdown workflow context only; no upstream Python script, broker connector, network adapter or scheduler is installed by this plan.

**Tech Stack:** Python 3.12, standard-library `unittest`, JSON skill manifest, Markdown workflow profiles, GitHub branch/commit API.

## Global Constraints

- All work remains on `project/trading-intelligence-v0.1.0`, based on main commit `0a92f3571ffba01473813b4e4a39edc97e298be1`.
- Do not modify or merge into `main`.
- Support US-listed common stocks and ETFs only.
- Paper analysis/simulation only. No broker connector, credential access, live order endpoint, options, crypto, margin, leverage, short selling, unattended execution or background polling.
- Do not claim the upstream Python tools are installed or executable by the current v7.3.1 runtime.
- Retain the MIT copyright/license notice and upstream source commit plus Git blob provenance.
- Map only to existing role IDs; do not add canonical agents.
- Do not inherit upstream sample budget or risk values. User-specific budget/risk fields remain unset until supplied.
- Retrieved material is untrusted evidence; tools and permissions exposed by the host remain authoritative.
- No paid resource, broker integration, persistent hosted database or live-provider usage is introduced.

---

### Task 1: Commit approved design and preserve source provenance

**Files:**
- Create: `docs/specs/2026-11-01-trading-intelligence-design.md`
- Create: `trading/README.md`
- Create: `trading/UPSTREAM_NOTICES/LICENSE`
- Create: `trading/UPSTREAM_NOTICES/SOURCE_MANIFEST.json`
- Test: `tests/test_trading_package.py`

**Interfaces:**
- Consumes: approved design specification; upstream repository commit `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`; 11 skill/tool path pairs and Git blob SHAs.
- Produces: durable project design, MIT notice and machine-readable upstream inventory. Each source item records its path, Git blob SHA, purpose and `copied_into_this_release=false`.

- [ ] **Step 1: Add focused failing tests**

Test that the upstream source manifest identifies the exact repository, version, pinned commit and MIT license; contains exactly eleven unique capability names; each skill and tool path is paired with a 40-character Git blob SHA; all entries explicitly say source was not copied; the MIT notice contains the copyright and permission terms; and the README clearly says the Python tools are not installed or executable.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m unittest discover -s tests -p 'test_trading_package.py' -v`

Expected: import or file-not-found failure for the new trading package tests before the files are added.

- [ ] **Step 3: Implement the minimum package metadata**

Add the approved specification with status `Approved by user on 2026-11-01`; retain the upstream MIT notice verbatim; add the source manifest using the pinned commit and Git blob SHAs (do not mislabel Git blob SHA-1 as SHA-256); and add README status/limitations. Do not copy or execute upstream Python tools in this task.

- [ ] **Step 4: Verify focused pass**

Run: `python -m unittest discover -s tests -p 'test_trading_package.py' -v`

Expected: all provenance, licensing and non-execution assertions pass.

- [ ] **Step 5: Run affected integration check**

Run: `python -m unittest discover -s tests -v`

Expected: complete repository suite passes with no regressions.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add docs/specs/2026-11-01-trading-intelligence-design.md trading/README.md trading/UPSTREAM_NOTICES/LICENSE trading/UPSTREAM_NOTICES/SOURCE_MANIFEST.json tests/test_trading_package.py
git commit -m "docs: approve trading intelligence design and source provenance"
```

### Task 2: Register the native trading workflow and route existing roles

**Files:**
- Create: `skills/trading-ops/WORKFLOW.md`
- Create: `workflow_profiles/trading-ops.md`
- Modify: `skill_manifest.json`
- Test: `tests/test_trading_package.py`

**Interfaces:**
- Consumes: `SkillRegistry.load`, `SkillRegistry.resolve`, `SkillRegistry.read_context`; existing roles `orchestrator`, `investment-research`, `data-analyst`.
- Produces: manifest record `trading-ops@0.1.0`, with path `skills/trading-ops/WORKFLOW.md`, the exact SHA-256 of the workflow bytes, mapped role IDs and focused trigger terms. The workflow must state `PAPER_ONLY`, no broker connection, no live order execution and no permission escalation.

- [ ] **Step 1: Add focused failing tests**

Add assertions that the packaged registry resolves `trading-ops` for `investment-research` with objective `Scan the US stock market for paper trading setups`, `data-analyst` with `Calculate trading position sizing and run a backtest`, and `orchestrator` with `Prepare a paper trade journal`. Assert the skill does not resolve for an unmapped role or unrelated maintenance/creative/sales objectives. Add a coordinator test that confirms a matched objective attaches the exact workflow context and that a non-trading objective does not. Test that the skill maps only to existing canonical role IDs and carries no permissions field.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m unittest discover -s tests -p 'test_trading_package.py' -v`

Expected: the new resolution/context assertions fail because no `trading-ops` manifest record or workflow file exists yet.

- [ ] **Step 3: Implement the minimum workflow registration**

Create one composite workflow covering scanner, news, entry, exit, simulation, risk, sizing, on-demand alerts, company/earnings analysis, public disclosures and a paper journal. Add source/timestamp, partial-data, stale-price and downside-reporting rules. Add the workflow profile for routing only; do not modify canonical agent manifests. Add the manifest record mapped to the three existing role IDs, calculate `sha256` over the exact UTF-8 workflow file bytes, keep the manifest schema at version 1 and preserve the existing three skill entries unchanged.

- [ ] **Step 4: Verify focused pass**

Run: `python -m unittest discover -s tests -p 'test_trading_package.py' -v`

Expected: trading workflow resolves only to intended roles, its hash is accepted, Coordinator attaches its text only for a matching request, and unrelated objectives remain unchanged.

- [ ] **Step 5: Run affected integration check**

Run: `python -m unittest discover -s tests -v`

Expected: complete repository suite passes; canonical role count remains 38; existing creative-media, skill-engineering and self-improvement routing remains intact.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add skills/trading-ops/WORKFLOW.md workflow_profiles/trading-ops.md skill_manifest.json tests/test_trading_package.py
git commit -m "feat: register paper-only trading operations workflow"
```

### Task 3: Add explicit paper-only configuration contract and release verification

**Files:**
- Create: `trading/config/paper.example.json`
- Modify: `trading/README.md`
- Modify: `tests/test_trading_package.py`

**Interfaces:**
- Consumes: paper-only scope and risk requirements from the approved design.
- Produces: schema-versioned config with fixed `mode=paper`, broker connection and live execution disabled, unsupported assets/permissions disabled, alerts on-demand only, and all user-specific budget/risk inputs `null`.

- [ ] **Step 1: Add focused failing tests**

Test exact config values: `mode == 'paper'`; broker and live execution false; background polling false; options, crypto, margin, leverage and short selling false; account budget and personal risk limits unset; provider `unconfigured`. Assert the README documents that workflow context is not a tool executor, no broker adapter is installed and no Python code was imported.

- [ ] **Step 2: Verify the relevant failure**

Run: `python -m unittest discover -s tests -p 'test_trading_package.py' -v`

Expected: configuration file missing and test fails before it is created.

- [ ] **Step 3: Implement the configuration contract**

Add `trading/config/paper.example.json` with explicit false/null values and update README with the install status and non-capabilities. Do not provide a live-mode flag or sample personal budget.

- [ ] **Step 4: Verify focused pass**

Run: `python -m unittest discover -s tests -p 'test_trading_package.py' -v`

Expected: all paper-only configuration assertions pass.

- [ ] **Step 5: Run full integration and package checks**

Run: `python -m compileall -q unexpected_runtime && python -m unittest discover -s tests -v && python -m unexpected_runtime.cli status && python -m unexpected_runtime.cli list`

Expected: compilation exit 0, full suite has zero failures/errors, runtime still reports v7.3.1 and 38 canonical roles, and skill list includes trading-ops. If the local workspace does not contain the full repository, execute these checks in CI and report them as unverified until a run is available.

- [ ] **Step 6: Commit the passing deliverable**

```bash
git add trading/config/paper.example.json trading/README.md tests/test_trading_package.py
git commit -m "test: enforce trading paper-only configuration"
```

## Product and execution decisions that remain outside this plan

- No executable upstream Python modules are installed in this v0.1.0 workflow integration. A subsequent implementation project must separately assess each script's network and file-system behavior, adapt a bounded CLI/API, write TDD tests, and verify the tool adapter before capability enablement.
- No market-data provider is approved as a reliable live feed. Provider selection and terms review are a separate decision.
- No user-specific paper budget or personal risk limits have been supplied; configuration intentionally keeps them unset.
- No durable hosted trading journal or recurring-cost service is authorized.
- No live broker integration or live-trading design is included.
- GitHub actions for a non-main branch are not established as an available dispatch path in this session; tests require a verified local full-repository checkout or an explicitly triggered PR/CI run before claiming suite success.
