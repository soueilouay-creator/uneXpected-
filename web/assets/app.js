(() => {
  "use strict";
  const state = { token: "", agents: [], providers: [], status: null, prompts: { items: [], categories: [], total: 0, offset: 0, loaded: false }, selectedPromptId: null };
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
    if (!response.ok) {
      const taskStatus = body?.result?.status;
      const taskError = body?.result?.error;
      const message = body?.error ||
        (body?.report?.failure_reason ? "Quality evaluation blocked: "+body.report.failure_reason :
        (taskStatus ? "Task "+taskStatus+(taskError ? ": "+taskError : " did not complete.") :
        ("Request failed ("+response.status+")")));
      const error = new Error(message); error.body = body; throw error;
    }
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
    $("proposal-agent").innerHTML=state.agents.map(a=>'<option value="'+esc(a.id)+'">'+esc(a.name)+" · "+esc(a.id)+'</option>').join("");
  }
  function renderProviders(items) {
    state.providers=items;
    const selector=$("task-provider");
    const previous=selector.value;
    selector.innerHTML='<option value="">Default configured route</option>'+items.map(p=>'<option value="'+esc(p.id)+'" '+(!p.configured?'disabled':'')+'>'+esc(p.id)+(p.default?' · default':'')+'</option>').join("");
    if(items.some(p=>p.id===previous&&p.configured))selector.value=previous;
    const qualitySelector=$("quality-provider");
    if(qualitySelector){
      const previousQuality=qualitySelector.value;
      const verified=items.filter(p=>p.live&&p.configured&&p.verified);
      qualitySelector.innerHTML='<option value="">Select a verified live route</option>'+verified.map(p=>'<option value="'+esc(p.id)+'">'+esc(p.id)+(p.model?' · '+esc(p.model):'')+'</option>').join("");
      if(verified.some(p=>p.id===previousQuality))qualitySelector.value=previousQuality;
      $("quality-evaluation-submit").disabled=verified.length===0;
    }
    $("provider-grid").innerHTML=items.length?items.map(p=>'<article><h4>'+esc(p.name)+'</h4><p>'+esc(p.model||"Model not disclosed")+'</p>'+readiness("Configuration",p.live?(p.configured?"Configured":"Not configured"):"Built-in test mode",!p.live||p.configured)+readiness("Live verification",p.live?(p.verified?"Verified":"Not verified"):"Not applicable",!p.live||p.verified)+(p.live&&p.configured?'<button class="button secondary provider-test" data-test-provider="'+esc(p.id)+'" type="button">Test connection</button>':'<small>Mock mode · not a live provider</small>')+'</article>').join(""):'<div class="empty">No provider adapters are available.</div>';
    syncLifecycleMode();
  }
  function syncLifecycleMode() {
    const providers=state.providers||[];
    const defaultProvider=providers.find(p=>p.default);
    const selectedId=$("task-provider").value||defaultProvider?.id;
    const selectedProvider=providers.find(p=>p.id===selectedId);
    const hasConfiguredLiveProvider=Boolean(selectedProvider?.live&&selectedProvider?.configured&&selectedProvider?.verified);
    const lifecycleOption=$("task-mode").querySelector('option[value="lifecycle"]');
    lifecycleOption.disabled=!hasConfiguredLiveProvider;
    lifecycleOption.textContent=hasConfiguredLiveProvider
      ? "Full verified lifecycle"
      : "Full verified lifecycle (requires a live AI provider)";
    if(!hasConfiguredLiveProvider&&$("task-mode").value==="lifecycle")$("task-mode").value="invoke";
  }
  async function loadPrompts({append=false}={}) {
    const query=$("prompt-search").value.trim();
    const category=$("prompt-category").value;
    const offset=append?state.prompts.offset:0;
    const params=new URLSearchParams({q:query,limit:"100",offset:String(offset)});
    if(category)params.set("category",category);
    $("prompt-search-button").disabled=true;
    try {
      const response=await api("/v1/prompts?"+params.toString());
      const previousCategory=category;
      state.prompts.categories=response.categories||state.prompts.categories;
      if(!state.prompts.loaded||$("prompt-category").options.length<=1){
        $("prompt-category").innerHTML='<option value="">All categories</option>'+state.prompts.categories.map(c=>'<option value="'+esc(c.id)+'">'+esc(c.name)+' · '+esc(c.count)+'</option>').join("");
        $("prompt-category").value=previousCategory;
      }
      state.prompts.items=append?state.prompts.items.concat(response.items||[]):(response.items||[]);
      state.prompts.total=response.total||0;
      state.prompts.offset=offset+(response.items||[]).length;
      state.prompts.loaded=true;
      $("prompt-nav-count").textContent=response.source?.advertised_prompt_count||"1,178";
      $("prompt-source-note").textContent=(response.source?.name||"AI Money Move Prompt Directory")+" · "+(response.source?.license_status||"licence not confirmed")+" · Titles/categories and attribution only; original prompt bodies are not reproduced.";
      $("prompt-results-count").textContent="Showing "+state.prompts.items.length+" of "+state.prompts.total+" matching titles";
      $("prompt-grid").innerHTML=state.prompts.items.length?state.prompts.items.map(item=>
        '<article class="prompt-card"><div class="prompt-card-meta"><span>'+esc(item.category)+'</span><span>'+esc(item.agent_id)+'</span></div><h4>'+esc(item.title)+'</h4><button class="button secondary prompt-use" type="button" data-prompt-id="'+esc(item.id)+'">Use in task →</button></article>'
      ).join(""):'<div class="empty">No matching prompt titles. Try another search or category.</div>';
      $("prompt-more-button").hidden=state.prompts.offset>=state.prompts.total||!response.items?.length;
    } catch(error) {
      $("prompt-grid").innerHTML='<div class="empty">Prompt catalogue unavailable: '+esc(error.message)+'</div>';
      toast(error.message);
    } finally { $("prompt-search-button").disabled=false; }
  }
  async function refresh() {
    $("refresh").disabled=true;
    try {
      const [status,agents,tasks,events,providers,caps,improvements,approvals,resources,qualityRuns]=await Promise.all([
        api("/v1/status"),api("/v1/agents"),api("/v1/tasks?limit=8"),api("/v1/events?limit=8"),
        api("/v1/providers"),api("/v1/capabilities"),api("/v1/improvements"),api("/v1/approvals"),
        api("/v1/resources?limit=100"),api("/v1/quality-evaluations?limit=20")
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
      $("resource-list").innerHTML=(resources.items||[]).length?(resources.items||[]).map(item=>row(item.name,item.expected_benefit+" · source: "+item.source_list_url,item.adoption_status)).join(""):'<div class="empty">No resource references are indexed yet.</div>';
      $("quality-evaluation-list").innerHTML=(qualityRuns.items||[]).length?(qualityRuns.items||[]).map(item=>{
        const failures=(item.failure_classes||[]).join(", ")||item.failure_reason||"No failure class";
        return row(item.evaluation_id,item.provider_route+" · "+item.execution_mode+" · "+failures,(item.status||"unknown")+" · "+Math.round((item.score||0)*100)+"%");
      }).join(""):'<div class="empty">No AI quality evaluations recorded yet.</div>';
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
    const titles={overview:"System overview",agents:"Agent registry",tasks:"Tasks & workflows",prompts:"Prompt Library",providers:"AI providers",capabilities:"Capabilities",intelligence:"Resource & AI quality",governance:"Governance",audit:"Audit & learning"};
    $("page-title").textContent=titles[name]||"System overview";
    if (name==="prompts"&&!state.prompts.loaded) loadPrompts();
    if (name==="tasks"||name==="audit"||name==="governance"||name==="intelligence") refresh();
  }
  document.querySelectorAll("[data-view]").forEach(link=>link.addEventListener("click",e=>{e.preventDefault();const name=link.dataset.view;showView(name);history.replaceState(null,"","#"+name);}));
  $("refresh").addEventListener("click",refresh);
  $("prompt-search-button").addEventListener("click",()=>loadPrompts());
  $("prompt-search").addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();loadPrompts();}});
  $("prompt-category").addEventListener("change",()=>loadPrompts());
  $("prompt-more-button").addEventListener("click",()=>loadPrompts({append:true}));
  $("prompt-grid").addEventListener("click",async e=>{
    const button=e.target.closest("[data-prompt-id]");
    if(!button)return;
    const promptId=button.dataset.promptId;
    button.disabled=true;button.textContent="Preparing…";
    try {
      const response=await api("/v1/prompts/"+encodeURIComponent(promptId));
      const item=response.item||{};
      state.selectedPromptId=item.id||null;
      $("task-agent").value=item.agent_id||"orchestrator";
      $("task-objective").value="Apply the selected uneXpected workflow: "+item.title+". Produce the requested deliverable for the context below. State assumptions and limitations.\n\nContext and requirements:\n";
      $("task-result").textContent="Selected: "+item.title+" · "+item.category+". Review and complete the task context before running.";
      showView("tasks");
      history.replaceState(null,"","#tasks");
      toast("Prompt selected. Review the task before running it.");
      $("task-objective").focus();
    } catch(error) {toast("Prompt could not be selected: "+error.message);}
    finally {button.disabled=false;button.textContent="Use in task →";}
  });
  $("task-agent").addEventListener("change",()=>{
    if(state.selectedPromptId){
      state.selectedPromptId=null;
      toast("Prompt selection cleared because the specialist role changed.");
    }
  });

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
  $("quality-evaluation-form").addEventListener("submit",async e=>{
    e.preventDefault();
    const button=$("quality-evaluation-submit");
    const route=$("quality-provider").value;
    const output=$("quality-evaluation-result");
    if(!route){output.textContent="Choose a verified live provider route first.";return;}
    button.disabled=true;output.textContent="Running the bounded read-only AI quality suite…";
    const renderReport=report=>{
      const failures=(report.failure_classes||[]).join(", ")||report.failure_reason||"No failed checks";
      output.textContent="Evaluation "+report.status+" · "+report.passed_cases+"/"+report.scenario_count+" cases passed · score "+Math.round((report.score||0)*100)+"% · "+report.execution_mode+". "+failures;
    };
    try {
      const response=await api("/v1/quality-evaluations",{method:"POST",body:JSON.stringify({provider_route:route})});
      renderReport(response.report||{status:"unknown"});
      toast("AI quality evaluation "+(response.report?.status||"finished"));
      await refresh();
    } catch(error) {
      if(error.body?.report)renderReport(error.body.report);
      else output.textContent="Evaluation could not run: "+error.message;
      toast(error.message);await refresh();
    } finally {button.disabled=false;}
  });
  $("agent-search").addEventListener("input",e=>{const q=e.target.value.toLowerCase();document.querySelectorAll("#agent-grid article").forEach(card=>card.hidden=!card.textContent.toLowerCase().includes(q));});
  $("task-provider").addEventListener("change",syncLifecycleMode);
  $("auth-form").addEventListener("submit",async e=>{e.preventDefault();state.token=$("auth-token").value.trim();$("auth-error").textContent="";await refresh();if(state.status)$("auth-overlay").classList.add("hidden");});
  $("proposal-form").addEventListener("submit",async e=>{
    e.preventDefault();const button=$("proposal-submit");button.disabled=true;$("proposal-result").textContent="Submitting proposal for review…";
    const payload={agent_id:$("proposal-agent").value,benchmark_id:$("proposal-benchmark").value.trim(),
      candidate_instruction:$("proposal-instruction").value,changes:$("proposal-changes").value,protected_fields:[]};
    try {
      const response=await api("/v1/improvements/propose",{method:"POST",body:JSON.stringify(payload)});
      $("proposal-result").textContent="Proposal created: "+(response.proposal?.proposal_id||"recorded")+" · "+(response.proposal?.status||"pending");
      toast("Improvement proposal created");await refresh();
    } catch(error) {$("proposal-result").textContent="Proposal rejected: "+error.message;toast(error.message);}
    finally {button.disabled=false;}
  });
  $("task-form").addEventListener("submit",async e=>{
    e.preventDefault();const button=$("task-submit");button.disabled=true;$("task-result").textContent="Submitting task to the governed coordinator…";
    const payload={agent_id:$("task-agent").value,objective:$("task-objective").value.trim()};
    if(state.selectedPromptId)payload.prompt_id=state.selectedPromptId;
    if($("task-provider").value)payload.provider_route=$("task-provider").value;
    try {
      const route=$("task-mode").value==="lifecycle"?"/v1/lifecycle":"/v1/invoke";
      const response=await api(route,{method:"POST",body:JSON.stringify(payload)});
      const result=response.result||{};
      $("task-result").innerHTML="<h3>"+esc(result.status||"Task returned")+"</h3><p>"+esc(result.verified_output||result.output||result.error||JSON.stringify(result))+"</p><p>Task ID: "+esc(result.task_id||"—")+"</p>";
      state.selectedPromptId=null;
      toast("Task response received");await refresh();
    } catch(error) {$("task-result").textContent="Task not completed: "+error.message;toast(error.message);}
    finally {button.disabled=false;}
  });
  if(location.hash){const name=location.hash.slice(1);if($("view-"+name))showView(name);}
  $("auth-overlay").classList.remove("hidden");
  window.setInterval(()=>{if(state.token)refresh();},60000);
})();