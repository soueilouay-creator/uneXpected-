import test from 'node:test';
import assert from 'node:assert/strict';
import { collectProviderCards, modeLabel, providerLabel } from '../mobile-release/providers.js';

test('labels direct OpenRouter answers with the actual router model and no fallback claim', () => {
  const cards = collectProviderCards({
    ok: true,
    mode: 'openrouter',
    results: {
      openrouter: {
        provider: 'openrouter',
        label: 'OpenRouter',
        status: 'LIVE · direct response',
        requestedModel: 'openrouter/free',
        model: 'nvidia/nemotron-3.5-lightning:free',
        latencyMs: 1820,
        text: 'Direct router answer.'
      }
    },
    fallback: { attempted: false, status: 'not_attempted' }
  });

  assert.equal(cards.length, 1);
  assert.equal(cards[0].label, 'OpenRouter');
  assert.equal(cards[0].provider, 'openrouter');
  assert.equal(cards[0].model, 'nvidia/nemotron-3.5-lightning:free');
  assert.equal(cards[0].requestedModel, 'openrouter/free');
  assert.equal(cards[0].latencyMs, 1820);
  assert.equal(cards[0].isFallback, false);
});

test('keeps primary failure and OpenRouter fallback as separate provider cards', () => {
  const cards = collectProviderCards({
    ok: true,
    mode: 'claude',
    results: {
      anthropic: { provider: 'anthropic', label: 'Claude', status: 'FAILED', error: 'Credit balance too low.' },
      openrouter: {
        provider: 'openrouter',
        label: 'OpenRouter fallback',
        status: 'LIVE · fallback response',
        requestedModel: 'openrouter/free',
        model: 'meta-llama/llama-3.3-70b-instruct:free',
        latencyMs: 2310,
        text: 'Fallback answer.'
      }
    },
    fallback: { attempted: true, provider: 'openrouter', status: 'succeeded', model: 'meta-llama/llama-3.3-70b-instruct:free' }
  });

  assert.equal(cards.length, 2);
  assert.equal(cards[0].key, 'anthropic');
  assert.equal(cards[0].error, 'Credit balance too low.');
  assert.equal(cards[1].key, 'openrouter');
  assert.equal(cards[1].isFallback, true);
  assert.equal(cards[1].isSynthesis, false);
  assert.equal(cards[1].model, 'meta-llama/llama-3.3-70b-instruct:free');
});

test('does not invent cards for missing providers and names all selectable routes', () => {
  assert.deepEqual(collectProviderCards({ ok: false, results: {} }), []);
  assert.equal(providerLabel('openai'), 'ChatGPT');
  assert.equal(providerLabel('anthropic'), 'Claude');
  assert.equal(providerLabel('openrouter'), 'OpenRouter');
  assert.equal(modeLabel('both'), 'Compare ChatGPT + Claude');
});
