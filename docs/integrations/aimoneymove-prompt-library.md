# AI Money Move seed — Prompt Intelligence integration

**Status:** Governed Prompt Intelligence implementation in draft PR #19  
**Source reviewed:** 2026-11-03  
**Source:** https://aimoneymove-prompts.netlify.app/  
**Publisher link shown by source metadata:** https://aimoneymove.com/

## Source snapshot

The directory advertises 1,178 prompt titles across 15 categories. The indexed metadata includes stable source IDs, title, category, source URL and a mapping to 13 existing canonical roles. The index is bundled as the first seed for the source-agnostic Prompt Intelligence subsystem.

## Reuse and attribution boundary

No explicit prompt-body reuse licence was found on the directory page during this review. The seed therefore stores titles, category labels, stable IDs, source attribution and canonical role mappings only. Original third-party prompt bodies are not reproduced. The runtime generates uneXpected-native starter instructions and never treats source metadata as instructions or policy.

This snapshot does not imply endorsement by the source publisher. Recheck source terms before any future import of original prompt text, logos, media or other expressive content.

## Unified runtime behavior

Prompt Intelligence is an in-process domain module in the existing Python runtime. It reuses the single Coordinator, canonical AgentRegistry (38 roles), PermissionPolicy, ApprovalVerifier, audit events and shared SQLite/PostgreSQL state. It is not a second service, database, coordinator or agent registry.

Every external source follows the same lifecycle:

1. Register source provenance (canonical URL, publisher, source type, terms/licence links and attribution).
2. Review rights and retention. New sources default to unknown rights and metadata-only retention.
3. Stage a bounded import batch (maximum 25 records); no import activates a prompt.
4. Store immutable prompt versions with source ID, content digest and attribution.
5. Map each candidate to an existing canonical specialist role.
6. Run deterministic prompt-injection/safety evaluation. Imported permissions are rejected and never grant tools or scopes.
7. Request action-bound host approval, then activate only the exact reviewed version if the trusted one-use approval verifies.
8. Monitor, version, supersede or retire records without silently replacing an active version.

Unknown or restricted rights permit metadata-only retention. Original source text is accepted only after a reviewed open licence, explicit permission or user-supplied basis is recorded with evidence and attribution.

## API and Command Center

- `GET /v1/prompts` and `GET /v1/prompts/{id}` search and retrieve active approved prompt versions; detail responses resolve the selected prompt's own source attribution.
- `GET /v1/prompt-intelligence/sources` and `POST /v1/prompt-intelligence/sources` list/register source records.
- `POST /v1/prompt-intelligence/sources/{id}/review` records the rights decision and retention policy.
- `POST /v1/prompt-intelligence/import` stages a metadata or rights-cleared batch.
- `GET /v1/prompt-intelligence/review-queue` lists staged and candidate versions.
- `POST /v1/prompt-intelligence/prompts/{id}/review` maps and evaluates a version.
- `GET /v1/prompt-intelligence/prompts/{id}/activation-details` returns canonical action details and digest for approval preparation.
- `POST /v1/prompt-intelligence/prompts/{id}/activate` accepts an approval context, but the server independently verifies it through the configured host verifier.

The Command Center's Prompt Intelligence workspace supports source registration, rights review, JSON batch import, source inventory, prompt review queue, canonical role mapping, activation details and active prompt search. It prepares the exact fields for the existing GitHub Actions approval workflow. A trusted administrator must approve the bot-authored request PR; the UI cannot self-approve. The runtime then validates the exact PR head, reviewer identity/permission, action digest, expiry and one-use ledger. If the host verifier is not configured, activation remains disabled and fails closed.

## Operational limits

- The source seed is local and static. There is no background crawler, scheduled refresh, external prompt execution or third-party connector installed.
- Discovery and metadata import do not authorize source-text retention, tool use, privileged actions or role creation.
- Prompt bodies and source metadata are untrusted data; they cannot override system/runtime policy.
- Sending messages, publishing, spending, payments, transfers, account changes, deployment and destructive actions remain separately gated.
- A CI pass is not proof of hosted deployment, live provider credentials, production database backup/restore or configured trusted reviewers.

## Verification evidence

The implementation candidate's CI run #672 completed successfully on code head `c7cde66e0c96bf89e0169211c7b31ff39aefd917`: 280 tests passed with one optional skip; Node syntax validation, PostgreSQL migration 003, SHA-256 integrity, Docker build, actual container UI/auth/38-role/task smoke, Prompt Intelligence catalogue/source/review-queue API checks and CLI smoke passed. Subsequent changes to repository documentation and the integrity inventory require their own current-head CI confirmation before merge.

Canonical review candidate: https://github.com/soueilouay-creator/uneXpected-/pull/19 (draft; not merged or deployed).
