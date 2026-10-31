# uneXpected v7.3.1 — Unified Self-Developing Agent Ecosystem

A local, executable, quality-gated runtime scaffold for 38 canonical agent roles. It preserves 37 legacy specialist profiles and adds one self-improvement governor. The 120 upstream README-linked templates are mapped as workflow capabilities, not separate agents.

## Quick start
```bash
python -m unexpected_runtime.cli status
python -m unexpected_runtime.cli list
python -m unexpected_runtime.cli run orchestrator --objective 'Plan a safe test task'
python -m unittest discover -s tests -v
```

Default provider is deterministic mock. Real provider access, external tools/connectors, hosting, scheduler, persistent production service and ChatGPT Project installation are not configured by this package. See `INSTALL.md`, `DEPLOY.md`, `CAPABILITY_MATRIX.md` and `THREAT_MODEL.md`.


## 7.3.0 — Governed workflow and capability upgrade (base release)

- Added a local hash-pinned workflow-skill registry for creative-media, skill-engineering and self-improvement context. Supplemental profiles remain outside `agents/`; the canonical registry still contains exactly 38 roles. Skill text is injected only for a mapped role and matching trigger, with a fresh SHA-256 check before provider dispatch.
- Added a provenance-aware capability registry backed by an additive SQLite table and audited lifecycle events. Records are metadata only; no external capability is executed by registry transitions. The `enabled` state requires an explicitly registered adapter verifier.
- Replaced caller-asserted approval flags with an `ApprovalVerifier` host interface and canonical action-digest binding. Privileged actions default to deny. Durable queued privileged actions remain denied until a host can persist and revalidate an approval reference.
- Bound improvement baselines and candidate evaluations to active-version, instruction and report fingerprints. Promotion now rejects stale baselines and records benchmark/scenario IDs, candidate hashes and approval state in the persisted evaluation report.
- Runtime package version is `7.3.0`. The default provider remains deterministic mock; no real provider, TAAFT adapter, external service, hosted scheduler, account integration or production approval authority is activated by this release.
- The historical v6 archive remains an optional test fixture; its integrity test is retained and skips only when that fixture is not supplied.


## GitHub approval authority (v7.3.1)

`Coordinator` auto-loads the GitHub PR verifier only when all required environment variables are present. Otherwise privileged actions remain denied. See `DEPLOY.md` for token permissions, PR approval flow, freshness rules and one-time consumption.
