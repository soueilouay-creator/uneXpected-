export const PROVIDER_MODES = Object.freeze(['openai', 'claude', 'openrouter', 'both', 'local']);

const LABELS = Object.freeze({
  openai: 'ChatGPT',
  anthropic: 'Claude',
  openrouter: 'OpenRouter',
  synthesis: 'uneXpected synthesis'
});

export function providerLabel(provider) {
  return LABELS[provider] || 'AI provider';
}

export function collectProviderCards(payload) {
  const results = payload?.results && typeof payload.results === 'object' ? payload.results : {};
  const cards = [];

  for (const key of ['openai', 'anthropic', 'openrouter', 'synthesis']) {
    const item = results[key];
    if (!item || typeof item !== 'object') continue;
    const text = typeof item.text === 'string' ? item.text.trim() : '';
    const error = typeof item.error === 'string' ? item.error : '';
    if (!text && !error && !item.status) continue;

    cards.push({
      provider: item.provider || (key === 'synthesis' ? 'openai' : key),
      key,
      label: item.label || providerLabel(key),
      status: item.status || (text ? 'Response received' : 'No response'),
      text,
      error,
      model: item.model || null,
      requestedModel: item.requestedModel || null,
      latencyMs: Number.isFinite(item.latencyMs) ? item.latencyMs : null,
      isFallback: key === 'openrouter' && (
        item.label === 'OpenRouter fallback' ||
        String(item.status || '').toLowerCase().includes('fallback') ||
        payload?.fallback?.attempted === true
      ),
      isSynthesis: key === 'synthesis'
    });
  }

  return cards;
}

export function modeLabel(mode) {
  return ({
    openai: 'ChatGPT',
    claude: 'Claude',
    openrouter: 'OpenRouter',
    both: 'Compare ChatGPT + Claude',
    local: 'Local tools'
  })[mode] || 'Choose a model';
}
