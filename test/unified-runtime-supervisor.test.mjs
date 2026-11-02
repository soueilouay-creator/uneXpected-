import test from 'node:test';
import assert from 'node:assert/strict';
import { buildRuntimeEnv, waitForRuntimeReady } from '../runtime-supervisor.mjs';

test('runtime child receives loopback-only port and distinct internal tokens', () => {
  const env = buildRuntimeEnv({
    PORT: '10000',
    UNEXPECTED_ACCESS_TOKEN: 'external-owner-token',
    OPENAI_API_KEY: 'provider-secret'
  }, 'internal-runtime-token', 8765);

  assert.equal(env.PORT, '8765');
  assert.equal(env.UNEXPECTED_RUNTIME_BIND_HOST, '127.0.0.1');
  assert.equal(env.UNEXPECTED_RUNTIME_PORT, '8765');
  assert.equal(env.UNEXPECTED_RUNTIME_API_TOKEN, 'internal-runtime-token');
  assert.equal(env.UNEXPECTED_GATEWAY_URL, 'http://127.0.0.1:10000/orchestrate');
  assert.equal(env.UNEXPECTED_GATEWAY_TOKEN, 'internal-runtime-token');
  assert.equal(env.UNEXPECTED_PROVIDER, 'ai_studio_gateway');
  assert.notEqual(env.UNEXPECTED_GATEWAY_TOKEN, env.UNEXPECTED_ACCESS_TOKEN);
  assert.equal(env.OPENAI_API_KEY, 'provider-secret');
});

test('runtime readiness succeeds only on an affirmative health response', async () => {
  let calls = 0;
  const ready = await waitForRuntimeReady({
    url: 'http://127.0.0.1:8765',
    attempts: 3,
    fetchImpl: async () => {
      calls += 1;
      return { ok: true, json: async () => ({ ok: true, version: '7.3.1' }) };
    },
    sleepImpl: async () => {}
  });
  assert.equal(ready.ok, true);
  assert.equal(ready.version, '7.3.1');
  assert.equal(calls, 1);
});

test('runtime readiness fails after the bounded retry budget', async () => {
  let calls = 0;
  await assert.rejects(() => waitForRuntimeReady({
    url: 'http://127.0.0.1:8765',
    attempts: 2,
    fetchImpl: async () => {
      calls += 1;
      return { ok: false, json: async () => ({ ok: false }) };
    },
    sleepImpl: async () => {}
  }), /runtime did not become ready/i);
  assert.equal(calls, 2);
});
