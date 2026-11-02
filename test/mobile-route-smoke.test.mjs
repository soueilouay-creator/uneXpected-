import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { once } from 'node:events';
import { setTimeout as delay } from 'node:timers/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
async function freePort(){
 const server=createServer();
 server.listen(0,'127.0.0.1');
 await once(server,'listening');
 const {port}=server.address();
 await new Promise((done,reject)=>server.close(error=>error?reject(error):done()));
 return port;
}
const hasGateway=await import('node:fs/promises').then(({access})=>access(resolve(root,'server.js')).then(()=>true,()=>false));

test('gateway serves the Phone 0.4.0 PWA without weakening existing authorization',{skip:!hasGateway&&'server.js is supplied by the host repository; HTTP smoke test runs in GitHub Actions'},async t=>{
 const port=await freePort(),token='test-only-token-not-a-production-secret';
 const child=spawn(process.execPath,['server.js'],{cwd:root,env:{...process.env,PORT:String(port),NODE_ENV:'test',UNEXPECTED_ACCESS_TOKEN:token},stdio:['ignore','pipe','pipe']});
 let stderr='';
 child.stderr.setEncoding('utf8');
 child.stderr.on('data',chunk=>stderr+=chunk);
 t.after(()=>{if(!child.killed)child.kill('SIGTERM')});
 const base='http://127.0.0.1:'+port;
 let health;
 for(let n=0;n<40;n++){
  try{health=await fetch(base+'/health');if(health.ok)break;}catch{}
  await delay(100);
 }
 assert.ok(health?.ok,'server did not start; stderr: '+stderr);
 const homepage=await fetch(base);
 assert.equal(homepage.status,200);
 assert.match(await homepage.text(),/uneXpected/i);

 const app=await fetch(base+'/mobile/');
 assert.equal(app.status,200);
 assert.match(app.headers.get('content-type'),/text\/html/);
 assert.match(app.headers.get('content-security-policy')||'',/default-src 'self'/);
 const html=await app.text();
 assert.match(html,/Your work\./);
 assert.match(html,/<script type="module" src="app\.js"><\/script>/);

 const paths=[
  ['/mobile/manifest.webmanifest',/manifest\+json/],
  ['/mobile/styles.css',/text\/css/],
  ['/mobile/app.js',/(javascript|ecmascript)/],
  ['/mobile/providers.js',/(javascript|ecmascript)/],
  ['/mobile/core.js',/(javascript|ecmascript)/],
  ['/mobile/db.js',/(javascript|ecmascript)/],
  ['/mobile/voice.js',/(javascript|ecmascript)/],
  ['/mobile/sw.js',/(javascript|ecmascript)/],
  ['/mobile/agents.json',/application\/json/],
  ['/mobile/skills.json',/application\/json/],
  ['/mobile/icons/icon.svg',/image\/svg\+xml/],
 ];
 for(const [path,type] of paths){
  const response=await fetch(base+path);
  assert.equal(response.status,200,path);
  assert.match(response.headers.get('content-type')||'',type,path);
 }
 const manifest=await (await fetch(base+'/mobile/manifest.webmanifest')).json();
 assert.equal(manifest.start_url,'/mobile/');
 assert.equal(manifest.scope,'/mobile/');
 const roles=await (await fetch(base+'/mobile/agents.json')).json();
 assert.equal(roles.agents.length,40);
 const skills=await (await fetch(base+'/mobile/skills.json')).json();
 assert.equal(skills.skills.length,2);
 const worker=await (await fetch(base+'/mobile/sw.js')).text();
 assert.match(worker,/unexpected-mobile-v0\.4\.0/);
 assert.doesNotMatch(worker,/\/orchestrate|\/test-provider|\/health/);

 const noSlash=await fetch(base+'/mobile');
 assert.equal(noSlash.status,200);
 assert.ok((noSlash.headers.get('content-type')||'').includes('text/html'));
 assert.equal((await fetch(base+'/mobile/%2e%2e/server.js')).status,404);
 const unauthorized=await fetch(base+'/orchestrate',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({task:'must not be executed',mode:'openai'})});
 assert.equal(unauthorized.status,401);
 const invalid=await fetch(base+'/orchestrate',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer wrong-token'},body:JSON.stringify({task:'must not be executed',mode:'openai'})});
 assert.equal(invalid.status,401);
});
