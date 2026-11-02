import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = path => readFile(resolve(root, path), 'utf8');

test('phone workspace uses responsive side navigation instead of a bottom tab bar', async () => {
  const html = await read('mobile/index.html');
  const css = await read('mobile/styles.css');
  assert.match(html, /id="sidebar"/);
  assert.match(html, /id="sidebarToggle"/);
  assert.match(html, /id="sidebarBackdrop"/);
  assert.match(html, /data-view="chat"/);
  assert.match(css, /\.sidebar/);
  assert.match(css, /@media\s*\(max-width:\s*760px\)/);
  assert.match(css, /prefers-reduced-motion/);
  assert.doesNotMatch(html, /class="bottom-nav"/);
});

test('phone conversation exposes ChatGPT, Claude and OpenRouter as selectable next-message routes', async () => {
  const html = await read('mobile/index.html');
  const app = await read('mobile/app.js');
  for (const provider of ['openai', 'claude', 'openrouter']) {
    assert.match(html, new RegExp('data-model="' + provider + '"'));
    assert.match(app, new RegExp("['\u0022]" + provider + "['\u0022]"));
  }
  assert.match(html, /id="modelMode"/);
  assert.match(app, /selectedModel/);
  assert.match(app, /mode:\s*selectedModel/);
  assert.match(app, /results\.openrouter/);
});

test('assistant messages preserve actual provider, model, latency and fallback provenance', async () => {
  const app = await read('mobile/app.js');
  assert.match(app, /requestedModel/);
  assert.match(app, /latencyMs/);
  assert.match(app, /fallback/);
  assert.match(app, /model/);
  assert.match(app, /provider/);
});

test('mobile access token remains in memory and never enters local backup settings', async () => {
  const app = await read('mobile/app.js');
  const core = await read('mobile/core.js');
  const db = await read('mobile/db.js');
  assert.match(app, /let sessionToken\s*=\s*''/);
  assert.match(app, /authorization:\s*['\"]Bearer/);
  assert.match(app, /sessionToken\s*=\s*event\.target\.value\.trim\(\)/);
  assert.doesNotMatch(app + core + db, /localStorage|sessionStorage/);
});


test('mobile navigation is hidden from focus when closed and manages keyboard focus when open', async () => {
  const html = await read('mobile/index.html');
  const app = await read('mobile/app.js');
  const css = await read('mobile/styles.css');
  assert.match(html, /class="skip-link" href="#mainContent"/);
  assert.match(html, /id="sidebar"[^>]*inert[^>]*aria-hidden="true"/);
  assert.match(html, /id="sidebarBackdrop"[^>]*aria-hidden="true"/);
  assert.match(app, /sidebar\.setAttribute\('inert', ''\)/);
  assert.match(app, /sidebar\.removeAttribute\('inert'\)/);
  assert.match(app, /#sidebarClose'\)\?\.focus\(\)/);
  assert.match(app, /#sidebarToggle'\)\?\.focus\(\)/);
  assert.match(app, /event\.shiftKey[\s\S]*last\.focus\(\)/);
  assert.match(css, /\.nav-item\s*\{\s*min-height:\s*2\.75rem/);
  assert.match(css, /\.composer-icon-button\s*\{\s*min-width:\s*2\.5rem;\s*min-height:\s*2\.75rem/);
});
