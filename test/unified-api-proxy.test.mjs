import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { createServer as createNetServer } from 'node:net';
import { setTimeout as delay } from 'node:timers/promises';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
async function freePort(){
  const server=createNetServer();
  server.listen(0,'127.0.0.1');
  await once(server,'listening');
  const port=server.address().port;
  await new Promise((done,reject)=>server.close(error=>error?reject(error):done()));
  return port;
}

test('owner-authenticated workspace requests are proxied only through the private runtime token',async t=>{
  const runtimePort=await freePort();
  const appPort=await freePort();
  const ownerToken='owner-test-token-'+'o'.repeat(32);
  const internalToken='internal-test-token-'+'i'.repeat(32);
  const received=[];
  const runtime=createServer(async(req,res)=>{
    received.push({method:req.method,path:req.url,authorization:req.headers.authorization});
    res.writeHead(200,{'content-type':'application/json'});
    if(req.method==='GET') return res.end(JSON.stringify({schema_version:1,records:[]}));
    let body='';
    for await(const chunk of req) body+=chunk;
    res.end(JSON.stringify({ok:true,body:JSON.parse(body)}));
  });
  runtime.listen(runtimePort,'127.0.0.1');
  await once(runtime,'listening');
  t.after(()=>runtime.close());

  const child=spawn(process.execPath,['server.js'],{cwd:root,env:{
    ...process.env,NODE_ENV:'production',PORT:String(appPort),
    UNEXPECTED_ACCESS_TOKEN:ownerToken,
    UNEXPECTED_RUNTIME_INTERNAL_URL:`http://127.0.0.1:${runtimePort}`,
    UNEXPECTED_RUNTIME_INTERNAL_TOKEN:internalToken
  },stdio:['ignore','ignore','pipe']});
  let stderr='';
  child.stderr.setEncoding('utf8');
  child.stderr.on('data',chunk=>stderr+=chunk);
  t.after(()=>{if(!child.killed)child.kill('SIGTERM');});
  const base=`http://127.0.0.1:${appPort}`;
  let health;
  for(let n=0;n<40;n++){
    try{health=await fetch(base+'/health');if(health.ok)break;}catch{}
    await delay(100);
  }
  assert.ok(health?.ok,'unified gateway failed readiness: '+stderr);
  const healthBody=await health.json();
  assert.equal(healthBody.runtime.storage,'postgresql');

  const denied=await fetch(base+'/v1/workspace/export');
  assert.equal(denied.status,401);

  const exported=await fetch(base+'/v1/workspace/export',{headers:{authorization:'Bearer '+ownerToken}});
  assert.equal(exported.status,200);
  assert.deepEqual(await exported.json(),{schema_version:1,records:[]});

  const invalid=await fetch(base+'/v1/workspace/import',{method:'POST',headers:{
    authorization:'Bearer '+ownerToken,'content-type':'application/json'
  },body:JSON.stringify({schema_version:1,device_id:'device-a',records:[],required_permissions:['publish']})});
  assert.equal(invalid.status,400);

  const imported=await fetch(base+'/v1/workspace/import',{method:'POST',headers:{
    authorization:'Bearer '+ownerToken,'content-type':'application/json'
  },body:JSON.stringify({schema_version:1,device_id:'device-a',records:[]})});
  assert.equal(imported.status,200);
  const result=await imported.json();
  assert.equal(result.ok,true);

  assert.ok(received.length>=2);
  assert.ok(received.every(item=>item.authorization==='Bearer '+internalToken));
  assert.ok(received.some(item=>item.method==='GET'&&item.path==='/v1/workspace/export'));
  assert.ok(received.some(item=>item.method==='POST'&&item.path==='/v1/workspace/import'));
});
