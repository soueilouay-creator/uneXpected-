# Core Router and Coordinator

The `orchestrator` is the canonical task router. `runtime/coordinator.py` implements the executable coordinator; `self-improvement-governor` separately governs changes. All 38 registered roles are invocable through one provider abstraction.

## Rule 1 — Investigate before declaring blocked

A failed step is an investigation trigger, not a terminal result. Before returning BLOCKED, the coordinator must preserve state; classify observed facts and unknowns; capture the exact error; identify the likely root cause; search relevant connected tools, files, repositories, documentation and alternative providers; compare safe options against the user's constraints; and perform bounded non-destructive checks. It must not repeat an unchanged failing attempt, bypass permissions, exceed budget, or perform paid/destructive/public/production/customer-facing actions without required approval. It may return BLOCKED only when the remaining dependency or authorization gap is evidenced and the report names what was checked, what remains unverified, why alternatives were not viable, and the precise condition required to continue. Record the root cause and a regression lesson through the governed improvement loop when the gap is repeatable.

## Routing algorithm
1. Parse objective, constraints, required deliverable and acceptance criteria.
2. Select the smallest useful primary role from `agent_manifest.json`; add supporting roles only for materially distinct work.
3. Check agent ID, permission scopes, budget, deadline, idempotency and cancellation before dispatch.
4. Enqueue a typed `TaskRequest`; invoke a bounded worker. Use `AgentMessage` for handoffs with sender, recipient, task ID, payload, provenance, permissions and depth.
5. Each agent receives only its own memory namespace plus reviewed shared knowledge; shared entries carry source and trust state.
6. Log task start, handoff, retries, permission decisions, completion and errors to SQLite audit events.
7. Verify outputs against role acceptance checks; record outcome/feedback. Send proposed changes through the governed improvement loop.

## Runtime bounds
- Worker and provider pools are bounded by `max_workers` (default 4).
- Deadline is enforced by a future timeout; cancellation is cooperative and cannot guarantee interrupting an arbitrary third-party network call.
- Retries are capped at 2; only safe, idempotent provider invocations are retried.
- Chains default to at most 4 handoffs; repeated agent IDs are rejected as a cycle.
- Each task has a step budget and each queue item has an idempotency key when supplied.
- Consequential permissions are deny-by-default and require an injected host `ApprovalVerifier` to authenticate the approver, validate scope, and verify the canonical action digest; `ApprovalContext` alone is not proof of identity.

## What “run them all” means
All 38 agents are registered and independently callable. A chain or task graph can invoke selected roles in one runtime. The package does not start all agents simultaneously, create independent model instances, or run continuously in the background.
