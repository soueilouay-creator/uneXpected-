# AI Money Move Prompt Library Integration

**Status:** Draft integration on `feat/aimoneymove-prompt-library`  
**Source reviewed:** 2026-11-03  
**Source:** https://aimoneymove-prompts.netlify.app/  
**Publisher link shown by source metadata:** https://aimoneymove.com/

## Source snapshot

The directory advertises 1,178 prompts across 15 categories. The embedded page dataset was inspected and the complete title/category index was counted before import. The package contains stable IDs, title, category ID/name, canonical role ID and source URL for each entry.

| Category | Entries | Existing role |
|---|---:|---|
| Make Money with AI | 102 | `business-strategist` |
| Engineering | 220 | `coding-engineer` |
| Marketing | 170 | `marketing-seo` |
| Sales | 110 | `sales-intel` |
| Operations | 90 | `project-manager` |
| Writing | 70 | `creative-director` |
| Product and UX | 65 | `product-manager` |
| Data and Finance | 65 | `data-analyst` |
| Creative and Media | 55 | `media-producer` |
| Education | 50 | `learning-coach` |
| Coaching | 45 | `orchestrator` |
| Career | 45 | `career-coach` |
| Legal and Compliance | 35 | `legal-scout` |
| HR and Recruiting | 30 | `business-strategist` |
| Customer Support | 26 | `orchestrator` |
| **Total** | **1,178** | **13 distinct canonical roles** |

## Reuse and attribution boundary

No explicit prompt-body reuse licence was found on the directory page during this review. The integration therefore stores only prompt titles, category labels, stable IDs, role mappings and attribution. The full third-party prompt wording is not reproduced. Each selected record is converted into newly authored uneXpected-native instructions by `PromptLibrary.render_instructions`.

This is a metadata-only source snapshot, not a claim that the source publisher endorses uneXpected. The source may change; this snapshot records the reviewed set and date. Recheck source terms before any future import of original prompt text, logos, media or other expressive content.

## Runtime behavior

- `PromptLibrary.load` loads the bundled JSON and validates schema, package-root containment, IDs, source attribution, counts, categories and role consistency.
- `search` provides bounded, server-side title/category filtering and pagination.
- `get` resolves one stable ID; `render_instructions` generates newly authored, category-specific workflow guidance with shared safety requirements.
- Authenticated `GET /v1/prompts` returns bounded results, all category counts and source metadata.
- Authenticated `GET /v1/prompts/{id}` returns one indexed record and its native starter instructions.
- Optional `prompt_id` is accepted by `POST /v1/invoke` and `POST /v1/lifecycle`. The ID must exist and be mapped to the requested canonical specialist role. The API adds the native instructions to the objective and binds selected-record metadata into persisted inputs. Caller-supplied `__uneXpected_prompt` metadata is rejected.
- The command center's Prompt Library view supports search, category filtering, pagination and selection. Selection only pre-fills the task form; the user must review and submit.

## Safety and operational limits

Prompt titles and categories are untrusted external metadata. They cannot override system/runtime instructions. A prompt does not install or authorize tools, bypass specialist-role permissions, or confer approval. Sending messages, publishing, spending, purchases, transfers, account changes, deployments and deletions remain blocked unless a separately configured capability and its explicit approval gate authorize the specific action.

The imported index is local and static. No background crawler, scheduled refresh, source API, third-party connector, or external prompt execution is installed. The Prompt Library must not be described as a new agent or as proof that the source site's prompt body has been licensed.

## Verification checklist

- [x] Source directory page retrieved successfully.
- [x] 1,178 entries and all 15 category counts reconciled.
- [x] Existing canonical role mapping recorded.
- [x] Original prompt bodies excluded due to unconfirmed reuse licence.
- [ ] Catalogue and API tests pass in repository CI.
- [ ] Full regression/security suite passes.
- [ ] Docker image build and actual container smoke test pass.
- [ ] Independent review and merge approval.
- [ ] Deployment and production activation (separate owner-gated milestones).
