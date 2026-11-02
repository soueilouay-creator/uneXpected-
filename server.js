import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { join } from 'node:path';
import { resolveMobileAsset } from './mobile-assets.mjs';
import { fileURLToPath } from 'node:url';
import { timingSafeEqual } from 'node:crypto';
import { TAAFT_MCP_URL, TAAFT_MCP_BETA, TAAFT_ALLOWED_TOOLS, buildOpenAITaaftTool, buildAnthropicTaaftConfig, withTaaftGuidance } from './taaft-integration.mjs';

const ROOT = fileURLToPath(new URL('.', import.meta.url));
const PORT = Number(process.env.PORT || 3000);
const OPENAI_MODEL = process.env.OPENAI_MODEL || 'gpt-4.1';
const ANTHROPIC_MODEL = process.env.ANTHROPIC_MODEL || 'claude-sonnet-4-5-20250929';
const OPENROUTER_MODEL = process.env.OPENROUTER_MODEL || 'openrouter/free';
const OPENROUTER_KEY = String(process.env.OPENROUTER_API_KEY || '').trim();
const ACCESS_TOKEN = process.env.UNEXPECTED_ACCESS_TOKEN || '';
const ANTHROPIC_WORKSPACE_ID = String(process.env.ANTHROPIC_WORKSPACE_ID || '').trim();
const OPENAI_KEY_NAMES = ['OPENAI_API_KEY', 'OPENAI_SECRET_KEY', 'OPENAI_API_TOKEN', 'OPENAI_KEY'];
const ANTHROPIC_KEY_NAMES = ['ANTHROPIC_API_KEY', 'ANTHROPIC_SECRET_KEY', 'ANTHROPIC_API_TOKEN', 'ANTHROPIC_KEY', 'CLAUDE_API_KEY'];
const providerVerified = { openai: false, anthropic: false, openrouter: false };
const rateBuckets = new Map();
const RATE_WINDOW_MS = 60_000;
const RATE_LIMIT = 30;
const MAX_BODY = 64 * 1024;
const TIMEOUT_MS = 90_000;
const MIME = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.svg': 'image/svg+xml', '.json': 'application/json; charset=utf-8' };

function isIdentifier(provider, value) {
  const v = String(value || '').trim();
  if (provider === 'openai') return /^key_/i.test(v);
  if (provider === 'anthropic') return /^wrkspc_/i.test(v);
  return false;
}
function resolveSecret(names, provider) {
  for (const name of names) {
    const value = String(process.env[name] || '').trim();
    if (!value || isIdentifier(provider, value)) continue;
    return { name, value };
  }
  return { name: null, value: '' };
}
const OPENAI_SECRET = resolveSecret(OPENAI_KEY_NAMES, 'openai');
const ANTHROPIC_SECRET = resolveSecret(ANTHROPIC_KEY_NAMES, 'anthropic');

function candidateStatus(names, provider) {
  const result = {};
  for (const name of names) {
    const value = String(process.env[name] || '').trim();
    result[name] = { present: Boolean(value), identifierOnly: Boolean(value) && isIdentifier(provider, value) };
  }
  return result;
}
function json(res, status, data) {
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
  res.end(JSON.stringify(data));
}
function safeError(err) {
  const s = String(err?.message || 'Provider request failed');
  return s.length > 500 ? s.slice(0, 500) : s;
}
function rateLimited(req) {
  const now = Date.now();
  const key = req.socket.remoteAddress || 'unknown';
  const bucket = rateBuckets.get(key) || { start: now, count: 0 };
  if (now - bucket.start >= RATE_WINDOW_MS) { bucket.start = now; bucket.count = 0; }
  bucket.count += 1;
  rateBuckets.set(key, bucket);
  if (rateBuckets.size > 5000) {
    for (const [k, v] of rateBuckets) if (now - v.start > RATE_WINDOW_MS) rateBuckets.delete(k);
  }
  return bucket.count > RATE_LIMIT;
}
function authorized(req) {
  if (!ACCESS_TOKEN) return false;
  const supplied = req.headers.authorization || '';
  const expected = 'Bearer ' + ACCESS_TOKEN;
  if (supplied.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(supplied), Buffer.from(expected));
}
async function readBody(req) {
  let data = '';
  for await (const chunk of req) {
    data += chunk;
    if (Buffer.byteLength(data) > MAX_BODY) throw Object.assign(new Error('Request body too large (maximum 64 KB).'), { status: 413 });
  }
  try { return JSON.parse(data || '{}'); }
  catch { throw Object.assign(new Error('Request body must be valid JSON.'), { status: 400 }); }
}
async function fetchTimed(url, options) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try { return await fetch(url, { ...options, signal: controller.signal }); }
  catch (e) {
    if (e.name === 'AbortError') throw new Error('Provider timed out after 90 seconds.');
    throw new Error('Could not reach provider. Check server network and provider status.');
  } finally { clearTimeout(timer); }
}
async function parseProvider(res, name) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = data?.error?.message || data?.error?.type || data?.message || ('HTTP ' + res.status);
    throw new Error(name + ' request failed (' + res.status + '): ' + String(msg).slice(0, 350));
  }
  return data;
}
async function callOpenAI(task, system = 'You are ChatGPT, one model in the uneXpected orchestration workspace. Give a direct, useful, well-structured answer.', options = {}) {
  const enableTaaft = options.enableTaaft !== false;
  if (!OPENAI_SECRET.value) throw new Error('OPENAI_API_KEY is not configured on the server. Checked: ' + OPENAI_KEY_NAMES.join(', ') + '. An OpenAI key ID (key_...) is not the secret value.');
  const start = Date.now();
  const requestBody = {
    model: OPENAI_MODEL,
    instructions: enableTaaft ? withTaaftGuidance(system) : system,
    input: task,
    store: false,
    max_output_tokens: 3000
  };
  if (enableTaaft) requestBody.tools = [buildOpenAITaaftTool()];
  const res = await fetchTimed('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: { authorization: 'Bearer ' + OPENAI_SECRET.value, 'content-type': 'application/json' },
    body: JSON.stringify(requestBody)
  });
  const data = await parseProvider(res, 'OpenAI');
  const text = data.output?.flatMap(item => item.content || []).filter(c => c.type === 'output_text').map(c => c.text).join('\n') || '';
  if (!text) throw new Error('OpenAI returned no text output.');
  return { text, latencyMs: Date.now() - start, model: data.model || OPENAI_MODEL };
}
async function callClaude(task, system = 'You are Claude, one model in the uneXpected orchestration workspace. Give a direct, useful, well-structured answer.', options = {}) {
  const enableTaaft = options.enableTaaft !== false;
  if (!ANTHROPIC_SECRET.value) throw new Error('ANTHROPIC_API_KEY is not configured on the server. Checked: ' + ANTHROPIC_KEY_NAMES.join(', ') + '. A workspace ID (wrkspc_...) is not the secret value.');
  const start = Date.now();
  const headers = { 'x-api-key': ANTHROPIC_SECRET.value, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' };
  let mcpConfig = {};
  if (enableTaaft) {
    headers['anthropic-beta'] = TAAFT_MCP_BETA;
    mcpConfig = buildAnthropicTaaftConfig();
  }
  if (ANTHROPIC_WORKSPACE_ID) headers['anthropic-workspace-id'] = ANTHROPIC_WORKSPACE_ID;
  const body = {
    model: ANTHROPIC_MODEL,
    max_tokens: 3000,
    system: enableTaaft ? withTaaftGuidance(system) : system,
    messages: [{ role: 'user', content: task }],
    ...mcpConfig
  };
  const res = await fetchTimed('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers,
    body: JSON.stringify(body)
  });
  const data = await parseProvider(res, 'Anthropic');
  const text = (data.content || []).filter(c => c.type === 'text').map(c => c.text).join('\n');
  if (!text) throw new Error('Claude returned no text output.');
  return { text, latencyMs: Date.now() - start, model: data.model || ANTHROPIC_MODEL };
}
async function callOpenRouter(task, system = 'You are the uneXpected free-model fallback. Be accurate, direct, and explicit about uncertainty. This fallback is not connected to TAAFT; never claim to have searched its catalog.') {
  if (!OPENROUTER_KEY) throw new Error('OPENROUTER_API_KEY is not configured. Add a free OpenRouter API key to enable the free-model fallback.');
  const start = Date.now();
  const res = await fetchTimed('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      authorization: 'Bearer ' + OPENROUTER_KEY,
      'content-type': 'application/json',
      'HTTP-Referer': 'https://unexpected-ai-studio.onrender.com',
      'X-Title': 'uneXpected AI Studio'
    },
    body: JSON.stringify({
      model: OPENROUTER_MODEL,
      messages: [{ role: 'system', content: system }, { role: 'user', content: task }],
      max_tokens: 3000
    })
  });
  const data = await parseProvider(res, 'OpenRouter');
  const raw = data.choices?.[0]?.message?.content;
  const text = typeof raw === 'string' ? raw : Array.isArray(raw) ? raw.map(part => typeof part?.text === 'string' ? part.text : '').filter(Boolean).join('\n') : '';
  if (!text) throw new Error('OpenRouter returned no text output.');
  return { text, latencyMs: Date.now() - start, model: data.model || OPENROUTER_MODEL };
}
function present(result, label, provider, requestedModel) {
  const base = { provider, label, requestedModel };
  return result.ok
    ? { ...base, status: 'LIVE · verified response', text: result.value.text, latencyMs: result.value.latencyMs, model: result.value.model }
    : { ...base, status: 'FAILED', error: safeError(result.error) };
}
async function attempt(fn) {
  try { return { ok: true, value: await fn() }; }
  catch (error) { return { ok: false, error }; }
}
async function orchestrate({ task, mode }) {
  const results = {};
  if (mode === 'openrouter') {
    const r = await attempt(() => callOpenRouter(task));
    providerVerified.openrouter = r.ok;
    results.openrouter = present(r, 'OpenRouter', 'openrouter', OPENROUTER_MODEL);
    if (r.ok) results.openrouter.status = 'LIVE · direct response';
  } else if (mode === 'openai') {
    const r = await attempt(() => callOpenAI(task));
    providerVerified.openai = r.ok;
    results.openai = present(r, 'ChatGPT', 'openai', OPENAI_MODEL);
  } else if (mode === 'claude') {
    const r = await attempt(() => callClaude(task));
    providerVerified.anthropic = r.ok;
    results.anthropic = present(r, 'Claude', 'anthropic', ANTHROPIC_MODEL);
  } else {
    const [o, c] = await Promise.all([attempt(() => callOpenAI(task)), attempt(() => callClaude(task))]);
    providerVerified.openai = o.ok;
    providerVerified.anthropic = c.ok;
    results.openai = present(o, 'ChatGPT', 'openai', OPENAI_MODEL);
    results.anthropic = present(c, 'Claude', 'anthropic', ANTHROPIC_MODEL);
    if (o.ok || c.ok) {
      const evidence = [
        o.ok ? 'CHATGPT RESPONSE:\n' + o.value.text : 'CHATGPT FAILED: ' + safeError(o.error),
        c.ok ? 'CLAUDE RESPONSE:\n' + c.value.text : 'CLAUDE FAILED: ' + safeError(c.error)
      ].join('\n\n---\n\n');
      const synthesisPrompt = 'User task:\n' + task + '\n\nTwo model results follow. Compare them, reconcile differences, retain important caveats, and give one actionable synthesis. Do not claim a model succeeded if its section says FAILED.\n\n' + evidence;
      const s = await attempt(() => callOpenAI(synthesisPrompt, 'You are the uneXpected synthesis layer. Combine independent model answers into a clear, accurate, actionable result. State uncertainty and disagreements. Never invent agreement.', { enableTaaft: false }));
      providerVerified.openai = s.ok;
      results.synthesis = present(s, 'uneXpected synthesis (ChatGPT)', 'openai', OPENAI_MODEL);
    }
  }

  // Run exactly one free-model fallback only when none of the requested primary
  // providers produced usable text. Never label the router response as synthesis.
  const hasPrimaryText = Boolean(results.openai?.text || results.anthropic?.text);
  let fallback = {
    attempted: false,
    provider: 'openrouter',
    status: 'not_attempted',
    requestedModel: OPENROUTER_MODEL,
    reason: mode === 'openrouter'
      ? 'OpenRouter was selected directly; no additional fallback request was made.'
      : 'At least one requested primary provider returned a usable response.'
  };

  if (mode !== 'openrouter' && !hasPrimaryText) {
    if (OPENROUTER_KEY) {
      const r = await attempt(() => callOpenRouter(task));
      providerVerified.openrouter = r.ok;
      results.openrouter = present(r, 'OpenRouter fallback', 'openrouter', OPENROUTER_MODEL);
      if (r.ok) {
        results.openrouter.status = 'LIVE · fallback response';
        fallback = {
          attempted: true,
          provider: 'openrouter',
          status: 'succeeded',
          requestedModel: OPENROUTER_MODEL,
          model: r.value.model,
          reason: 'All requested primary providers failed.'
        };
      } else {
        fallback = {
          attempted: true,
          provider: 'openrouter',
          status: 'failed',
          requestedModel: OPENROUTER_MODEL,
          model: null,
          reason: 'All requested primary providers failed; the OpenRouter fallback also failed.'
        };
      }
    } else {
      providerVerified.openrouter = false;
      results.openrouter = {
        provider: 'openrouter',
        label: 'OpenRouter fallback',
        status: 'NOT CONFIGURED',
        requestedModel: OPENROUTER_MODEL,
        error: 'All requested primary providers failed. OPENROUTER_API_KEY is not configured on the server; no fallback request was sent.'
      };
      fallback = {
        attempted: false,
        provider: 'openrouter',
        status: 'not_configured',
        requestedModel: OPENROUTER_MODEL,
        reason: 'All requested primary providers failed, but OPENROUTER_API_KEY is not configured.'
      };
    }
  }

  const ok = Boolean(results.openai?.text || results.anthropic?.text || results.openrouter?.text || results.synthesis?.text);
  return { ok, mode, results, fallback, completedAt: new Date().toISOString() };
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://' + (req.headers.host || 'localhost'));
    if (req.method === 'GET' && url.pathname === '/health') {
      return json(res, 200, {
        ok: true,
        service: 'uneXpected AI Studio',
        mode: ACCESS_TOKEN ? 'live-ready' : 'locked',
        authConfigured: Boolean(ACCESS_TOKEN),
        providers: {
          openai: { configured: Boolean(OPENAI_SECRET.value), verified: providerVerified.openai, model: OPENAI_MODEL, credentialSource: OPENAI_SECRET.name, candidates: candidateStatus(OPENAI_KEY_NAMES, 'openai') },
          anthropic: { configured: Boolean(ANTHROPIC_SECRET.value), verified: providerVerified.anthropic, model: ANTHROPIC_MODEL, credentialSource: ANTHROPIC_SECRET.name, candidates: candidateStatus(ANTHROPIC_KEY_NAMES, 'anthropic'), workspaceConfigured: Boolean(ANTHROPIC_WORKSPACE_ID) },
          openrouter: { configured: Boolean(OPENROUTER_KEY), verified: providerVerified.openrouter, model: OPENROUTER_MODEL }
        },
        relatedProviderVariables: Object.keys(process.env).filter(name => /OPENAI|ANTHROPIC|CLAUDE|OPENROUTER|API_KEY/i.test(name)).sort().map(name => ({ name, present: Boolean(String(process.env[name] || '').trim()) })),
        metadataVariables: { openaiKeyIdPresent: Boolean(process.env.OPENAI_API_KEY_ID), anthropicWorkspaceIdPresent: Boolean(ANTHROPIC_WORKSPACE_ID || process.env.ANTHROPIC_WORKSPACE_ID) },
        note: 'No secret values are returned. Configured means a usable-looking secret value is present; verified becomes true only after a real provider request.',
        integrations: {
          taaft: {
            enabled: true,
            endpoint: TAAFT_MCP_URL,
            access: 'public read-only catalog; no TAAFT account login or API key',
            allowlistedTools: TAAFT_ALLOWED_TOOLS.length,
            connectedProviders: ['openai', 'anthropic'],
            liveVerified: false
          }
        }
      });
    }
    if (req.method === 'GET' && url.pathname === '/mobile') {
      res.writeHead(308, { location: '/mobile/', 'cache-control': 'no-store' });
      return res.end();
    }
    if (req.method === 'GET' && url.pathname.startsWith('/mobile/')) {
      const asset = resolveMobileAsset(url.pathname, join(ROOT, 'public'));
      if (!asset) return json(res, 404, { error: 'Not found.' });
      try {
        const content = await readFile(asset.filePath);
        res.writeHead(200, {
          'content-type': asset.contentType,
          'cache-control': asset.cacheControl,
          'x-content-type-options': 'nosniff',
          'content-security-policy': "default-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; object-src 'none'",
          'permissions-policy': 'microphone=(self)'
        });
        return res.end(content);
      } catch (error) {
        if (error.code === 'ENOENT' || error.code === 'EISDIR') return json(res, 404, { error: 'Not found.' });
        throw error;
      }
    }
    if (req.method === 'GET' && url.pathname === '/openrouter-ui.js') {
      res.writeHead(200, { 'content-type': MIME['.js'], 'cache-control': 'no-store', 'x-content-type-options': 'nosniff' });
      return res.end(await readFile(join(ROOT, 'openrouter-ui.js')));
    }
    if (req.method === 'GET' && url.pathname === '/') {
      const page = await readFile(join(ROOT, 'public', 'index.html'), 'utf8');
      const script = '<script src="/openrouter-ui.js" defer></script>';
      const closingBody = page.toLowerCase().lastIndexOf('</body>');
      const html = closingBody >= 0 ? page.slice(0, closingBody) + script + page.slice(closingBody) : page + script;
      res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store', 'content-security-policy': "default-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'" });
      return res.end(html);
    }
    if (req.method === 'GET' && url.pathname === '/app.js') {
      res.writeHead(200, { 'content-type': MIME['.js'], 'cache-control': 'no-store' });
      return res.end(await readFile(join(ROOT, 'public', 'app.js')));
    }
    if (req.method === 'GET' && url.pathname === '/styles.css') {
      res.writeHead(200, { 'content-type': MIME['.css'], 'cache-control': 'no-store' });
      return res.end(await readFile(join(ROOT, 'public', 'styles.css')));
    }
    if (req.method === 'POST' && ['/orchestrate', '/test-provider'].includes(url.pathname)) {
      if (rateLimited(req)) return json(res, 429, { error: 'Rate limit exceeded. Wait one minute and try again.' });
      if (!authorized(req)) return json(res, 401, { error: ACCESS_TOKEN ? 'Unauthorized. Provide the configured bearer token.' : 'Server is locked: set UNEXPECTED_ACCESS_TOKEN (32+ random characters) before using provider endpoints.' });
      const body = await readBody(req);
      if (url.pathname === '/test-provider') {
        const provider = body.provider;
        if (provider === 'openai') {
          const r = await attempt(() => callOpenAI('Reply with exactly: OpenAI connection verified.', undefined, { enableTaaft: false }));
          providerVerified.openai = r.ok;
          return json(res, r.ok ? 200 : 502, r.ok ? { ok: true, provider, model: r.value.model, latencyMs: r.value.latencyMs, text: r.value.text } : { ok: false, provider, error: safeError(r.error) });
        }
        if (provider === 'anthropic') {
          const r = await attempt(() => callClaude('Reply with exactly: Claude connection verified.', undefined, { enableTaaft: false }));
          providerVerified.anthropic = r.ok;
          return json(res, r.ok ? 200 : 502, r.ok ? { ok: true, provider, model: r.value.model, latencyMs: r.value.latencyMs, text: r.value.text } : { ok: false, provider, error: safeError(r.error) });
        }
        if (provider === 'openrouter') {
          const r = await attempt(() => callOpenRouter('Reply with exactly: Free fallback connection verified.'));
          providerVerified.openrouter = r.ok;
          return json(res, r.ok ? 200 : 502, r.ok ? { ok: true, provider, model: r.value.model, latencyMs: r.value.latencyMs, text: r.value.text } : { ok: false, provider, error: safeError(r.error) });
        }
        return json(res, 400, { error: 'provider must be openai, anthropic, or openrouter.' });
      }
      const task = typeof body.task === 'string' ? body.task.trim() : '';
      const mode = body.mode || 'both';
      if (!task) return json(res, 400, { error: 'task is required.' });
      if (task.length > 16000) return json(res, 413, { error: 'Task exceeds 16,000 characters.' });
      if (!['both', 'openai', 'claude', 'openrouter'].includes(mode)) return json(res, 400, { error: 'mode must be both, openai, claude, or openrouter.' });
      const result = await orchestrate({ task, mode });
      return json(res, result.ok ? 200 : 502, result);
    }
    if (req.method === 'GET' && url.pathname === '/favicon.ico') { res.writeHead(204); return res.end(); }
    return json(res, 404, { error: 'Not found.' });
  } catch (error) {
    return json(res, error.status || 500, { error: safeError(error) });
  }
});
server.listen(PORT, '0.0.0.0', () => {
  if (process.env.NODE_ENV !== 'test') process.stdout.write('uneXpected AI Studio listening on ' + PORT + '\n');
});
export { server, orchestrate, callOpenAI, callClaude, resolveSecret, candidateStatus };
