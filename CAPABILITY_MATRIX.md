# Capability Matrix

| Capability | Runtime status in this package | Required for | Gate / truth rule |
|---|---|---|---|
| Provider chat | Available via deterministic mock; real adapter code present but unconfigured | Every agent invocation | Real provider requires environment configuration and successful smoke test |
| Local SQLite state/event log | Available locally | Queue, memory, idempotency, audit, proposals | Persistent only on the configured host/filesystem |
| Web/current-source tools | Not wired into this runtime | Research/web roles | ChatGPT web tools may be available outside runtime; not implicitly passed to it |
| Browser actions / third-party connectors | Not configured | Browser, CRM, mail, repository integrations | Require connector authorization and per-action permission |
| Code execution beyond this Python scaffold | Not granted to agents by default | Coding/test workflows | Host tool adapter and sandbox required |
| External video/audio/image rendering | Not configured | Media/voice workflows | A production plan is not a rendered asset |
| Background scheduler / notifications | Not configured | Monitoring and recurring workflows | Requires host, scheduler, persistent state and authorized notification connector |
| Live payment/trade/publish/mail/repo-write/delete/deploy/account changes | Denied by default | Consequential actions | Authorized tool + explicit human approval required |
| Benchmark measurements | Fixed offline tests available; live-model quality measurements not run | Self-improvement | Mock results cannot establish real model quality |
| Human approval channel | Not connected to this CLI | Protected change promotion | Caller must provide explicit approval context; default is deny |
