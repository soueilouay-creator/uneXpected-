(() => {
  "use strict";
  const state = { token: "", agents: [], status: null };
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const time = (v) => { if (!v) return "—"; const n=Number(v); const d=new Date(n>1e12?n:n*1000); return Number.isNaN(d.getTime())?String(v):d.toLocaleString(); };
  function toast(message) { const el=$("toast"); el.textContent=message; el.classList.add("show"); window.setTimeout(()=>el.classList.remove("show"),2500); }
  async function api(path, options={}) {
    const headers = new Headers(options.headers || {});
    headers.set("Authorization","Bearer "+state.token);
    if (options.body) headers.set("Content-Type","application/json");
    const response=await fetch(path,{...options,headers,cache:"no-store"});
    const type=response.headers.get("content-type")||"";
    const body=type.includes("application/json")?await response.json():await response.text();
    if (!response.ok) throw new Error(body?.error||("Request failed ("+response.status+")"));
    return body;
  }
  function setConnected(ok) {
    $("connection").textContent=ok?"● Connected":"● API unavailable";
    $("connection").style.color=ok?"#59d9c1":"#ff7d8b";
    $("side-dot").className="dot "+(ok?"ok":"bad");
    $("side-health").textContent=ok?"Runtime connected":"Runtime unavailable";
  }
  function row(title, detail, meta) {
    return '<div class="list-row"><div><div class="list-title">'+esc(title)+'</div><div class="list-detail">'+esc(detail||"")+'</div></div><div class="list-meta">'+esc(meta||"")+'</div></div>';
  }
  function readiness(name,value,ok) {
    return '<div class="list-row"><div class="list-title">'+esc(name)+'</div><div class="list-meta"><span class="state '+(ok?"ok":"")+'">'+esc(value)+'</span></div></div>';
  }
  function renderAgents() {
    $("agent-grid").innerHTML=state.agents.length?state.agents.map(a=>'<article><div class="agent-id">'+esc(a.id)+'</div><h4>'+esc(a.name)+'</h4><p>'+esc(a.objective||a.capability_label||"Governed specialist role")+'</p><div class="tags"><span class="tag">'+esc(a.version||"version —")+'</span><span class="tag">'+esc(a.status||"registered")+'</span></div></article>').join(""):'<div class="empty">Agent registry unavailable.</div>';
    $("task-agent").innerHTML=state.agents.map(a=>'<option value="'+esc(a.id)+'">'+esc(a.name)+" · "+esc(a.id)+'</option>').join("");
  }
  function renderProviders(items) {
    const selector=$("task-provider");
    const previous=selector.value;
    selector.innerHTML='<option value="">Default configured route</option>'+items.map(p=>'<option value="'+esc(p.id)+'" '+(!p.configured?'disabled':'')+'>'+esc(p.id)+(p.default?' · default':'')+'</option>').join("");
    if(items.some(p=>p.id===previous&&p.configured))selector.value=previous;
    $("provider-grid").innerHTML=items.length?items.map(p=>'<article><h4>'+esc(p.name)+'</h4><p>'+esc(p.model||"Model not disclosed")+'</p>'+readiness("Credential",p.configured?"Configured":"Not configured",p.configured)+readiness("Live verification",p.verified?"Verified":"Not verified",p.verified)+(p.live&&p.configured?'<button class="button secondary provider-test" data-test-provider="'+esc(p.id)+'" type="button">Test connection</button>':'<small>Mock mode · not a live provider</small>')+'</article>').join(""):'<div class="empty">No provider adapters are available.</div>';
  }
  async function refresh() {
    $("refresh").disabled=true;
    try {
      const [status,agents,tasks,events,providers,caps,improvements,approvals]=await Promise.all([
        api("/v1/status"),api("/v1/agents"),api("/v1/tasks?limit=8"),api("/v1/events?limit=8"),
        api("/v1/providers"),api("/v1/capabilities"),api("/v1/improvements"),api("/v1/approvals")
      ]);
      state.status=status; state.agents=agents.items||[];
      $("metric-health").textContent=status.health?.status||"Ready";
      $("health-note").textContent=status.health?.detail||"Runtime status received";
      $("metric-agents").textContent=agents.count??state.agents.length;
      $("nav-count").textContent=agents.count??state.agents.length;
      $("version").textContent=status.version||"—";
      const provider=(providers.providers||[])[0]||{};
      $("metric-provider").textContent=provider.name||status.provider||"Unavailable";
      $("provider-note").textContent=provider.verified?"Live request verified":provider.configured?"Configured · not verified":"Not configured";
      $("readiness").innerHTML=[
        readiness("HTTP application",status.health?.status||"healthy",status.health?.ok!==false),
        readiness("Agent registry",String(agents.count??0)+" roles",agents.count===38),
        readiness("State store",status.storage?.status||"local adapter",status.storage?.healthy===true),
        readiness("Provider route",provider.verified?"verified":provider.configured?"configured only":"unavailable",provider.verified===true),
        readiness("Privileged actions",status.governance?.privileged_actions||"disabled",false)
      ].join("");
      $("recent-events").innerHTML=(events.items||[]).length?events.items.map(e=>row(e.event_type,e.agent_id||e.task_id||"",time(e.ts))).join(""):'<div class="empty">No events recorded yet.</div>';
      $("audit-events").innerHTML=$("recent-events").innerHTML;
      $("task-list").innerHTML=(tasks.items||[]).length?tasks.items.map(t=>row(t.objective||t.task_id,t.agent_id+" · "+t.status,time(t.created_at))).join(""):'<div class="empty">No tasks recorded yet.</div>';
      $("capability-list").innerHTML=(caps.items||[]).length?caps.items.map(c=>row(c.name||c.capability_id,c.source||c.description||"",c.status||"registered")).join(""):'<div class="empty">No capabilities registered. Catalog entries do not imply live integrations.</div>';
      $("improvement-list").innerHTML=(improvements.items||[]).length?improvements.items.map(p=>row(p.proposal_id,p.agent_id+" · "+p.changes,p.status)).join(""):'<div class="empty">No improvement proposals recorded.</div>';
      $("approval-list").innerHTML=(approvals.items||[]).length?approvals.items.map(a=>row(a.approval_id,a.permission,a.status)).join(""):'<div class="empty">'+esc(approvals.message||"No pending approval records are exposed. Privileged execution remains disabled.")+'</div>';
      $("approval-state").textContent=status.governance?.approval_authority||"Not verified";
      $("replay-state").textContent=status.governance?.replay_protection||"Not verified";
      $("recovery-state").textContent=status.storage?.recovery||"Not verified";
      $("updated").textContent="Updated "+new Date().toLocaleTimeString();
      renderAgents(); renderProviders(providers.providers||[]); setConnected(true);
    } catch(error) {
      setConnected(false);
      if (error.message==="Unauthorized."||error.message==="Unauthorized") {
        $("auth-overlay").classList.remove("hidden");
        $("auth-error").textContent="The access token was rejected.";
      } else toast(error.message);
    } finally { $("refresh").disabled=false; }
  }
  function showView(name) {
    document.querySelectorAll(".view").forEach(v=>v.classList.toggle("active",v.id==="view-"+name));
    document.querySelectorAll(".nav").forEach(v=>v.classList.toggle("active",v.dataset.view===name));
    const titles={overview:"System overview",agents:"Agent registry",tasks:"Tasks & workflows",providers:"AI providers",capabilities:"Capabilities",governance:"Governance",audit:"Audit & learning"};
    $("page-title").textContent=titles[name]||"System overview";
    if (name==="tasks"||name==="audit"||name==="governance") refresh();
  }
  document.querySelectorAll("[data-view]").forEach(link=>link.addEventListener("click",e=>{e.preventDefault();const name=link.dataset.view;showView(name);history.replaceState(null,"","#"+name);}));
  $("refresh").addEventListener("click",refresh);
  $("provider-grid").addEventListener("click",async e=>{
    const button=e.target.closest("[data-test-provider]");
    if(!button)return;
    button.disabled=true;button.textContent="Testing…";
    try {
      const result=await api("/v1/providers/test",{method:"POST",body:JSON.stringify({provider_route:button.dataset.testProvider})});
      toast(result.provider+" verified in "+result.latency_ms+" ms");
      await refresh();
    } catch(error) { toast(error.message); }
    finally { button.disabled=false;button.textContent="Test connection"; }
  });
  $("agent-search").addEventListener("input",e=>{const q=e.target.value.toLowerCase();document.querySelectorAll("#agent-grid article").forEach(card=>card.hidden=!card.textContent.toLowerCase().includes(q));});
  $("auth-form").addEventListener("submit",async e=>{e.preventDefault();state.token=$("auth-token").value.trim();$("auth-error").textContent="";await refresh();if(state.status)$("auth-overlay").classList.add("hidden");});
  $("task-form").addEventListener("submit",async e=>{
    e.preventDefault();const button=$("task-submit");button.disabled=true;$("task-result").textContent="Submitting task to the governed coordinator…";
    const payload={agent_id:$("task-agent").value,objective:$("task-objective").value.trim()};
    if($("task-provider").value)payload.provider_route=$("task-provider").value;
    try {
      const route=$("task-mode").value==="lifecycle"?"/v1/lifecycle":"/v1/invoke";
      const response=await api(route,{method:"POST",body:JSON.stringify(payload)});
      const result=response.result||{};
      $("task-result").innerHTML="<h3>"+esc(result.status||"Task returned")+"</h3><p>"+esc(result.verified_output||result.output||result.error||JSON.stringify(result))+"</p><p>Task ID: "+esc(result.task_id||"—")+"</p>";
      toast("Task response received");await refresh();
    } catch(error) {$("task-result").textContent="Task not completed: "+error.message;toast(error.message);}
    finally {button.disabled=false;}
  });
  if(location.hash){const name=location.hash.slice(1);if($("view-"+name))showView(name);}
  $("auth-overlay").classList.remove("hidden");
  window.setInterval(()=>{if(state.token)refresh();},60000);
})();