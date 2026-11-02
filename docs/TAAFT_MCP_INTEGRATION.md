# TAAFT MCP integration

## What this adds

uneXpected AI Studio connects its OpenAI Responses API and Anthropic Messages API calls to the official public TAAFT MCP endpoint:

`https://theresanaiforthat.com/mcp/`

The connection is read-only. The provider APIs can discover and retrieve public catalog entries for AI tools, MCP servers, tasks, models, companies, robots, devices, organizations, investors, countries, events, fundraises, research papers, and repositories.

The integration uses an explicit allowlist of 28 search/detail operations. Only `search_*` and `get_*` catalog methods are enabled. Both provider adapters use the same allowlist. Newly added upstream tools remain disabled until reviewed and added deliberately.

## Provider behavior

- **OpenAI:** the Responses API receives a remote MCP tool definition with `allowed_tools` set to the allowlist. Read-only catalog calls do not require an approval round-trip.
- **Anthropic:** the Messages API receives an MCP connector and an MCP toolset with all tools disabled by default, then only the same allowlisted tools explicitly enabled. The request uses the `mcp-client-2026-09-15` beta header.
- **OpenRouter fallback:** remains unchanged and is not connected to TAAFT. The fallback must not claim to have searched TAAFT.

The connector is exposed only on normal model tasks. The separate provider-connection test buttons intentionally omit MCP so a TAAFT outage cannot make a valid OpenAI or Claude API key appear broken. The uneXpected synthesis call also omits TAAFT to avoid a redundant lookup after the two primary model responses.

## Privacy and account scope

TAAFT's public MCP endpoint does not require a TAAFT login or API key. This is **public catalog access**, not authentication to a personal TAAFT account. It does not expose private bookmarks, saved lists, billing, profile settings, or other account-only data.

System guidance tells models to use concise, generic search terms only and never send passwords, API keys, tokens, private personal data, confidential business information, or the full conversation to TAAFT. Catalog content is treated as untrusted data. Returned TAAFT URLs should be preserved exactly.

TAAFT documents limits of 30 requests per minute and 1,000 requests per UTC day per source IP. Use searches only when the request benefits from tool discovery; avoid repeated exploratory calls.

## Verification

Run the focused integration tests from the repository root:

```sh
node --test test/taaft-integration.test.mjs
```

Check `/health` for the static `integrations.taaft` configuration summary. That indicates that the integration is included in the deployed build; it is not proof that either provider key is valid or that a live TAAFT tool call has succeeded. A live end-to-end check requires a real OpenAI or Anthropic API request and may incur provider usage charges.
