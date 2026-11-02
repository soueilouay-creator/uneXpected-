const scenario = process.env.PROVIDER_TEST_SCENARIO || 'fallback-success';

function response(status, payload) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' }
  });
}

globalThis.fetch = async (input) => {
  const url = String(input);
  let provider;
  if (url.includes('api.openai.com')) provider = 'openai';
  else if (url.includes('api.anthropic.com')) provider = 'anthropic';
  else if (url.includes('openrouter.ai')) provider = 'openrouter';
  else throw new Error('Unexpected provider URL in test: ' + url);

  process.stdout.write('PROVIDER_MOCK_CALL:' + provider + '\n');

  if (provider === 'openai' && scenario === 'primary-success') {
    return response(200, {
      model: 'gpt-4.1',
      output: [{ content: [{ type: 'output_text', text: 'Primary OpenAI answer.' }] }]
    });
  }

  if (provider === 'openrouter' && scenario === 'fallback-success') {
    return response(200, {
      model: 'nvidia/nemotron-3.5-lightning:free',
      choices: [{ message: { content: 'OpenRouter fallback answer.' } }]
    });
  }

  if (provider === 'openrouter' && scenario === 'fallback-failure') {
    return response(429, { error: { message: 'Mock OpenRouter rate limit.' } });
  }

  return response(provider === 'openai' ? 429 : 400, {
    error: { message: provider === 'openai' ? 'Mock OpenAI credits exhausted.' : 'Mock Anthropic balance too low.' }
  });
};
