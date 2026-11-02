import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const read=p=>readFile(resolve(root,p),'utf8');

test('installable page references its PWA manifest and external app modules',async()=>{
 const html=await read('mobile/index.html');
 const manifest=JSON.parse(await read('mobile/manifest.webmanifest'));
 assert.match(html,/<link rel="manifest" href="manifest\.webmanifest">/);
 assert.match(html,/<link rel="stylesheet" href="styles\.css">/);
 assert.match(html,/<script type="module" src="app\.js"><\/script>/);
 assert.equal(manifest.id,'/mobile/');
 assert.equal(manifest.start_url,'/mobile/');
 assert.equal(manifest.scope,'/mobile/');
 assert.equal(manifest.display,'standalone');
 assert.equal(manifest.orientation,'any');
 assert.ok(manifest.icons.some(icon=>icon.src==='icons/icon-192.png' && icon.sizes==='192x192'));
 assert.ok(manifest.icons.some(icon=>icon.src==='icons/icon-512.png' && icon.sizes==='512x512'));
});

test('mobile application is split into parseable ES modules',async()=>{
 const files=['app.js','core.js','db.js','voice.js'];
 for(const file of files){
  const source=await read('mobile/'+file);
  assert.ok(source.length>100, file+' should not be empty');
  assert.match(source,/\b(import|export)\b/,file+' should be an ES module');
 }
 const html=await read('mobile/index.html');
 assert.doesNotMatch(html,/<script>([\s\S]*?)<\/script>/);
});

test('phone includes the complete v7.1 profile index and workflow skills',async()=>{
 const registry=JSON.parse(await read('mobile/agents.json'));
 const skills=JSON.parse(await read('mobile/skills.json'));
 assert.equal(registry.sourceCount,40);
 assert.equal(registry.agents.length,40);
 assert.ok(registry.agents.some(a=>a.id==='self-improvement-governor'));
 assert.ok(registry.agents.some(a=>a.id==='creative-media-studio'));
 assert.ok(registry.agents.some(a=>a.id==='skill-engineering'));
 assert.equal(skills.count,2);
 assert.equal(skills.skills.length,2);
 assert.match(registry.runtimeStatus,/profile|not.*running|not.*verified/i);
});

test('gateway bearer token remains in memory and is excluded from backups',async()=>{
 const app=await read('mobile/app.js');
 const core=await read('mobile/core.js');
 const database=await read('mobile/db.js');
 const html=await read('mobile/index.html');
 assert.match(app,/let sessionToken\s*=\s*''/);
 assert.match(app,/authorization.*Bearer/);
 assert.match(app,/sessionToken=event\.target\.value\.trim\(\)/);
 assert.match(html,/id="accessToken" type="password"[^>]*autocomplete="off"/);
 assert.doesNotMatch(app+core+database,/localStorage|sessionStorage/);
 assert.ok(core.includes('settings: safeSettings(data?.settings)'));
 assert.ok(core.includes('settings: safeSettings(data?.settings)'));
});

test('context sharing is opt-in and improvements enter context only after planning approval',async()=>{
 const html=await read('mobile/index.html');
 const app=await read('mobile/app.js');
 const core=await read('mobile/core.js');
 assert.match(html,/<input id="shareContext" type="checkbox">/);
 assert.match(app,/const contextConsent = \$\('#shareContext'\)\?\.checked === true/);
 assert.match(app,/const context = contextConsent \?/);
 assert.ok(core.includes('settings: safeSettings(data?.settings)'));
 assert.match(html,/Approved ideas are for planning only; they do not change code or deploy automatically/);
});

test('voice modules support recognition, speech synthesis and user-selected language',async()=>{
 const html=await read('mobile/index.html');
 const app=await read('mobile/app.js');
 const voice=await read('mobile/voice.js');
 assert.match(voice,/environment\?\.SpeechRecognition \|\| environment\?\.webkitSpeechRecognition/);
 assert.match(voice,/environment\?\.speechSynthesis/);
 assert.match(voice,/environment\?\.SpeechSynthesisUtterance/);
 assert.match(app,/createSpeechRecognition\(/);
 assert.match(app,/speakText\(/);
 assert.match(html,/id="voiceLanguage"/);
 assert.match(html,/id="voiceModeBtn"/);
 assert.match(html,/id="voiceInputBtn"/);
 assert.match(html,/id="autoSpeakToggle"/);
});

test('offline service worker caches only same-origin mobile GET resources',async()=>{
 const worker=await read('mobile/sw.js');
 assert.match(worker,/event\.request\.method !== 'GET'/);
 assert.match(worker,/url\.origin !== self\.location\.origin/);
 assert.match(worker,/url\.pathname\.startsWith\('\/mobile\/'\)/);
 assert.match(worker,/caches\.open\(CACHE_NAME\)/);
 assert.doesNotMatch(worker,/\/orchestrate|\/test-provider|\/health/);
});

test('gateway status uses text output and safely escapes status labels',async()=>{
 const app=await read('mobile/app.js');
 assert.match(app,/function escapeHtml\(/);
 assert.match(app,/node\.textContent = message/);
 assert.match(app,/box\.textContent =/);
 assert.match(app,/Gateway check failed:/);
});
