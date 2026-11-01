# uneXpected Trading Intelligence v0.1.0

This project overlay adds a hash-pinned trading research workflow for US-listed stocks and ETFs. The workflow is adapted from `Jakeschincariol/day-trader-skill` v2.0.0, upstream commit `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`, under the MIT license. See `UPSTREAM_NOTICES/LICENSE` and `UPSTREAM_NOTICES/SOURCE_MANIFEST.json`.

## Installed in this branch

- `skills/trading-ops/WORKFLOW.md`: the composite workflow attached by the existing uneXpected skill registry.
- `workflow_profiles/trading-ops.md`: routing and permission boundaries using existing canonical roles.
- `config/paper.example.json`: fixed paper-only example with personal budget/risk values intentionally unset.
- `UPSTREAM_NOTICES/`: attribution and pinned source inventory.

The single composite skill covers the upstream scanner, news, entry, exit, simulation, risk, budget, alerts, analyst, public-disclosure and broker-ticket workflow concepts. It does not create eleven new canonical agents.

## Important non-capabilities

The source Python executables are inventoried by Git blob SHA but are not copied, installed, executed or exposed as tools in v0.1.0. uneXpected's current skill loader injects verified text context; it is not a Python execution engine. No live or paper broker connector, network market-data adapter, background poller, hosted paper journal or real order endpoint is installed by this overlay. Do not claim those features are operational.

The initial paper-only configuration disables all trading execution. Any future executable adapters must be separately implemented, reviewed and tested behind an explicit allowlist and deterministic interface. Live brokerage use is outside this release and requires a separate design and approval.

## Local verification

Run the full repository suite with `python -m unittest discover -s tests -v`. This release's focused package tests also verify workflow provenance, license presence, fixed paper-only defaults and skill-registry routing/hash behavior.
