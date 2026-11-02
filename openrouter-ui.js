(() => {
  'use strict';
  function addControl() {
    const testRow = document.getElementById('testClaude')?.parentElement;
    const accessInput = document.getElementById('accessToken');
    if (!testRow || !accessInput) return;

    // The production page may render this control in its HTML already. Reuse it
    // and always attach the handler; only create a button when one is absent.
    let button = document.getElementById('testOpenRouter');
    if (!button) {
      button = document.createElement('button');
      button.id = 'testOpenRouter';
      button.type = 'button';
      button.className = 'secondary';
      button.textContent = 'Test OpenRouter API';
      button.setAttribute('aria-label', 'Test OpenRouter free fallback API');
      testRow.append(button);
    }

    let message = document.getElementById('openrouterTestMessage');
    if (!message) {
      message = document.createElement('p');
      message.id = 'openrouterTestMessage';
      message.className = 'hint';
      message.setAttribute('aria-live', 'polite');
      message.textContent = 'Free fallback test is separate from ChatGPT and Claude.';
      const existingMessage = document.getElementById('providerTestMessage');
      if (existingMessage) existingMessage.after(message);
      else testRow.after(message);
    }

    const claudeStep = document.getElementById('claudeStatus')?.closest('.step');
    if (claudeStep && !document.getElementById('openrouterStatus')) {
      const step = document.createElement('div');
      step.className = 'step';
      const number = document.createElement('div');
      number.className = 'num';
      number.textContent = '3';
      const content = document.createElement('div');
      const title = document.createElement('strong');
      title.textContent = 'OpenRouter free fallback';
      const status = document.createElement('p');
      status.id = 'openrouterStatus';
      status.textContent = 'Checking…';
      content.append(title, status);
      step.append(number, content);
      claudeStep.after(step);
      const orchestratorNumber = document.getElementById('serverStatus')?.closest('.step')?.querySelector('.num');
      if (orchestratorNumber) orchestratorNumber.textContent = '4';
    }

    button.style.flex = '1 1 160px';
    if (!button.__openrouterHandlerAttached) {
      button.addEventListener('click', runTest);
      button.__openrouterHandlerAttached = true;
    }
    refreshStatus();
  }

  function setMessage(value) {
    const target = document.getElementById('openrouterTestMessage');
    if (target) target.textContent = value;
  }

  async function refreshStatus() {
    const target = document.getElementById('openrouterStatus');
    if (!target) return;
    try {
      const response = await fetch('/health', { cache: 'no-store' });
      if (!response.ok) throw new Error('Health check returned HTTP ' + response.status);
      const data = await response.json();
      const provider = data.providers?.openrouter;
      if (!provider?.configured) target.textContent = 'Not configured on Render · add OPENROUTER_API_KEY';
      else if (provider.verified) target.textContent = 'Configured · last test verified in this server session';
      else target.textContent = 'Configured · not yet verified (run the test below)';
    } catch {
      target.textContent = 'Could not read OpenRouter status';
    }
  }

  async function runTest() {
    const button = document.getElementById('testOpenRouter');
    const input = document.getElementById('accessToken');
    let token = input?.value?.trim() || '';
    if (!token) {
      try { token = window.__UX_ACCESS_TOKEN || sessionStorage.getItem('ux_access_token') || ''; } catch {}
    }
    if (!token) {
      setMessage('Enter your Render UNEXPECTED_ACCESS_TOKEN in Access settings and click “Use token for this tab” first. It is not an OpenRouter API key.');
      input?.focus();
      return;
    }

    button.disabled = true;
    button.textContent = 'Testing OpenRouter…';
    setMessage('Sending one real test request to OpenRouter. This does not call ChatGPT or Claude.');
    try {
      const response = await fetch('/test-provider', {
        method: 'POST',
        headers: { 'content-type': 'application/json', authorization: 'Bearer ' + token },
        body: JSON.stringify({ provider: 'openrouter' }),
        cache: 'no-store'
      });
      const result = await response.json().catch(() => ({}));
      if (response.ok && result.ok) {
        setMessage('Verified · ' + (result.model || 'OpenRouter model') + ' · ' + result.latencyMs + ' ms. This is the OpenRouter free-model router, not ChatGPT or Claude.');
      } else if (response.status === 401) {
        setMessage('Studio access denied. Check the server access token under Access settings and save it for this tab.');
      } else {
        setMessage(result.error || 'OpenRouter test failed with HTTP ' + response.status + '.');
      }
    } catch (error) {
      setMessage('Could not reach the Studio test endpoint: ' + String(error?.message || error));
    } finally {
      button.disabled = false;
      button.textContent = 'Test OpenRouter API';
      await refreshStatus();
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', addControl, { once: true });
  else addControl();
})();
