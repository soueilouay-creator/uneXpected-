# uneXpected v7.3.1 — Unified Self-Developing Agent Ecosystem

A local, executable, quality-gated runtime scaffold for 38 canonical agent roles. It preserves 37 legacy specialist profiles and adds one self-improvement governor. The 120 upstream README-linked templates are mapped as workflow capabilities, not separate agents.

## Quick start

```bash
python -m unexpected_runtime.cli status
python -m unexpected_runtime.cli list
python -m unexpected_runtime.cli run orchestrator --objective 'Plan a safe test task'
python -m unittest discover -s tests -v
```

The default provider is deterministic mock. The optional AI Studio gateway connects the Python runtime to the existing OpenAI/Anthropic/OpenRouter service without copying provider API keys into Python. See docs/RUNTIME_CONNECTIVITY.md for secret handoff, authenticated runtime API, model modes, tool boundaries and Render limitations.

## 7.3.0 — Governed workflow and capability upgrade

- Added hash-pinned workflow-skill registry for creative-media, skill-engineering and self-improvement context.
- Added provenance-aware capability metadata registry; metadata transitions do not execute external tools.
- Replaced caller-asserted approval flags with a host ApprovalVerifier interface and canonical action-digest binding. Privileged actions default to deny.
- Bound self-improvement evaluation to active-version, instruction and report fingerprints.

## 7.3.1 — GitHub approval authority

The optional GitHub PR verifier validates the reviewed request document, current reviewer identity and permission, exact action digest, expiry and single-use replay ledger. It remains fail-closed until host configuration, persistent storage and live approval/replay tests are complete.

Real provider access, external tools, hosting and persistent production service must be configured and live-tested separately. No production deployment or live provider call is implied by source code or a passing mock test.
