import test from 'node:test';
import assert from 'node:assert/strict';
import {
  TAAFT_MCP_URL,
  TAAFT_MCP_BETA,
  TAAFT_ALLOWED_TOOLS,
  buildOpenAITaaftTool,
  buildAnthropicTaaftConfig,
  withTaaftGuidance,
} from '../taaft-integration.mjs';

test('OpenAI connector is remote MCP and restricted to read-only catalog tools', () => {
  const tool = buildOpenAITaaftTool();
  assert.equal(tool.type, 'mcp');
  assert.equal(tool.server_url, TAAFT_MCP_URL);
  assert.equal(tool.require_approval, 'never');
  assert.deepEqual(tool.allowed_tools, TAAFT_ALLOWED_TOOLS);
  assert.ok(tool.allowed_tools.every((name) => /^(search|get)_/.test(name)));
  assert.equal('authorization' in tool, false);
});

test('Anthropic connector uses the same URL and enables only the read-only allowlist', () => {
  const config = buildAnthropicTaaftConfig();
  assert.deepEqual(config.mcp_servers, [{ type: 'url', url: TAAFT_MCP_URL, name: 'taaft' }]);
  assert.equal(config.tools.length, 1);
  const toolset = config.tools[0];
  assert.equal(toolset.type, 'mcp_toolset');
  assert.equal(toolset.mcp_server_name, 'taaft');
  assert.deepEqual(toolset.default_config, { enabled: false });
  assert.deepEqual(Object.keys(toolset.configs).sort(), [...TAAFT_ALLOWED_TOOLS].sort());
  assert.ok(Object.values(toolset.configs).every((entry) => entry.enabled === true));
  assert.equal(TAAFT_MCP_BETA, 'mcp-client-2026-09-15');
});

test('TAAFT guidance restricts use and protects private data', () => {
  const result = withTaaftGuidance('Base system prompt.');
  assert.ok(result.startsWith('Base system prompt.'));
  assert.match(result, /concise and generic/);
  assert.match(result, /passwords, API keys, access tokens/);
  assert.match(result, /untrusted data/);
  assert.match(result, /does not authenticate to the user's personal TAAFT account/);
  assert.match(result, /do not invent listings/);
});
