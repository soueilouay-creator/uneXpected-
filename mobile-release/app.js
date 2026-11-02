import { openDatabase, LocalStore, requestPersistentStorage } from './db.js';
import { routeAgent, buildTaskEnvelope, parseLocalCommand, createBackupPayload, parseBackupPayload, defaultAppSettings, MAX_USER_TASK_CHARS } from './core.js';
import { createSpeechRecognition, speakText, getAvailableVoices } from './voice.js';
import { collectProviderCards, modeLabel } from './providers.js';

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const id = () => globalThis.crypto?.randomUUID?.() || `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
const now = () => new Date().toISOString();
let store;
let activeConversationId = null;
let activeProjectId = null;
let selectedProfileId = null;
let selectedSkillId = null;
let activeProfileTab = 'agents';
let selectedModel = 'openai';
let agents = [];
let skills = [];
let sessionToken = '';
let appSettings = { id: 'main' };
let installPrompt = null;
let activeRecognition = null;
let voiceModeEnabled = false;
let voiceBusy = false;
let requestBusy = false;
let toastTimer;

function toast(message) {
  const node = $('#toast');
  if (!node) return;
  node.textContent = message;
  node.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('show'), 2800);
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
}

function formatDate(value, options = { month: 'short', day: 'numeric' }) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

function gatewayBase() {
  const raw = $('#gatewayUrl')?.value.trim() || appSettings.gatewayUrl || '';
  return raw ? raw.replace(/\/$/, '') : location.origin;
}

function setConnection(text, tone = 'local', detail = '') {
  const label = $('#connectionLabel');
  const dot = $('#connectionDot');
  const mobile = $('#mobileConnection');
  if (label) label.textContent = text;
  if (dot) {
    dot.dataset.tone = tone;
    dot.title = text;
  }
  if (mobile) {
    const mobileDot = mobile.querySelector('.connection-dot');
    if (mobileDot) mobileDot.dataset.tone = tone;
    mobile.title = text;
  }
  if ($('#connectionDetail')) $('#connectionDetail').textContent = detail || (tone === 'online' ? 'Gateway reachable' : tone === 'warning' ? 'Check connection settings' : 'Saved on this device');
}

function isMobileNavigation() {
  return window.matchMedia('(max-width: 760px)').matches;
}

function syncSidebarForViewport() {
  const sidebar = $('#sidebar');
  const backdrop = $('#sidebarBackdrop');
  const toggle = $('#sidebarToggle');
  if (!sidebar) return;
  if (!isMobileNavigation()) {
    sidebar.classList.remove('open');
    sidebar.removeAttribute('inert');
    sidebar.removeAttribute('aria-hidden');
    backdrop?.classList.remove('open');
    backdrop?.setAttribute('aria-hidden', 'true');
    toggle?.setAttribute('aria-expanded', 'false');
    $('#mainContent')?.removeAttribute('inert');
    document.body.classList.remove('drawer-open');
  } else if (!sidebar.classList.contains('open')) {
    sidebar.setAttribute('inert', '');
    sidebar.setAttribute('aria-hidden', 'true');
  }
}

function closeSidebar() {
  const sidebar = $('#sidebar');
  const wasOpen = sidebar?.classList.contains('open') === true;
  sidebar?.classList.remove('open');
  $('#sidebarBackdrop')?.classList.remove('open');
  $('#sidebarBackdrop')?.setAttribute('aria-hidden', 'true');
  $('#sidebarToggle')?.setAttribute('aria-expanded', 'false');
  $('#mainContent')?.removeAttribute('inert');
  document.body.classList.remove('drawer-open');
  if (isMobileNavigation()) {
    sidebar?.setAttribute('inert', '');
    sidebar?.setAttribute('aria-hidden', 'true');
    if (wasOpen) $('#sidebarToggle')?.focus();
  }
}

function toggleSidebar(force) {
  const sidebar = $('#sidebar');
  const backdrop = $('#sidebarBackdrop');
  const open = typeof force === 'boolean' ? force : !sidebar?.classList.contains('open');
  if (!sidebar) return;
  if (!isMobileNavigation()) {
    syncSidebarForViewport();
    return;
  }
  if (open) {
    sidebar.removeAttribute('inert');
    sidebar.setAttribute('aria-hidden', 'false');
    sidebar.classList.add('open');
    backdrop?.classList.add('open');
    backdrop?.setAttribute('aria-hidden', 'false');
    $('#mainContent')?.setAttribute('inert', '');
    $('#sidebarToggle')?.setAttribute('aria-expanded', 'true');
    document.body.classList.add('drawer-open');
    $('#sidebarClose')?.focus();
  } else {
    closeSidebar();
  }
}

function showView(name) {
  $$('.view').forEach(view => view.classList.toggle('active', view.id === `view-${name}`));
  $$('.nav-item').forEach(button => {
    const active = button.dataset.view === name;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  closeSidebar();
  if (name === 'home') refreshHome();
  if (name === 'chat') refreshChats();
  if (name === 'projects') refreshProjects();
  if (name === 'memory') refreshMemories();
  if (name === 'agents') renderAgents();
  if (name === 'settings') refreshSettings();
  if (name !== 'chat') window.scrollTo({ top: 0, behavior: 'smooth' });
}

function setSelectedModel(mode) {
  if (!['openai', 'claude', 'openrouter', 'both', 'local'].includes(mode)) mode = 'openai';
  selectedModel = mode;
  $('#modelMode').value = mode;
  $$('[data-model]').forEach(button => {
    const active = button.dataset.model === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  const compare = $('#compareBtn');
  compare?.classList.toggle('active', mode === 'both');
  compare?.setAttribute('aria-pressed', String(mode === 'both'));
  const local = $('#localModeBtn');
  local?.classList.toggle('active', mode === 'local');
  local?.setAttribute('aria-pressed', String(mode === 'local'));
  const hint = $('#modelModeHint');
  const hintText = {
    openai: 'ChatGPT selected.',
    claude: 'Claude selected.',
    openrouter: 'OpenRouter selected.',
    both: 'Compare ChatGPT + Claude.',
    local: 'Local tools only.'
  };
  if (hint) hint.textContent = hintText[mode] || '';
  const route = $('#routeCaption');
  if (route && !requestBusy) route.textContent = `Next message · ${modeLabel(mode)}`;
  if (mode !== 'local' && !sessionToken) {
    $('#voiceStatus').textContent = 'Add your gateway access token in Control center to send.';
  }
}

function openDialog({ title, eyebrow = 'WORKSPACE', fields, saveLabel = 'Save', onSave }) {
  const dialog = $('#simpleDialog');
  $('#dialogTitle').textContent = title;
  $('#dialogEyebrow').textContent = eyebrow;
  $('#dialogSaveBtn').textContent = saveLabel;
  $('#dialogBody').innerHTML = fields.map(field => {
    const label = `<label class="dialog-field" for="dlg-${escapeHtml(field.name)}"><span>${escapeHtml(field.label)}</span>`;
    const required = field.required ? ' required' : '';
    const placeholder = escapeHtml(field.placeholder || '');
    if (field.type === 'textarea') return `${label}<textarea id="dlg-${escapeHtml(field.name)}" name="${escapeHtml(field.name)}" placeholder="${placeholder}"${required}></textarea></label>`;
    return `${label}<input id="dlg-${escapeHtml(field.name)}" name="${escapeHtml(field.name)}" type="${escapeHtml(field.type || 'text')}" placeholder="${placeholder}"${required}></label>`;
  }).join('');
  dialog.showModal();
  $('#dialogForm').onsubmit = async event => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(event.currentTarget).entries());
    const missing = fields.find(field => field.required && !String(values[field.name] || '').trim());
    if (missing) { toast(`${missing.label} is required.`); return; }
    try {
      await onSave(values);
      dialog.close();
    } catch (error) {
      toast(error.message || 'Could not save this item.');
    }
  };
}

async function refreshHome() {
  const [projects, chats, memories] = await Promise.all([
    store.list('projects'), store.list('conversations'), store.list('memories')
  ]);
  $('#statProjects').textContent = projects.length;
  $('#statChats').textContent = chats.length;
  $('#statMemory').textContent = memories.length;
  const items = [
    ...chats.slice(0, 5).map(item => ({
      kind: 'chat', id: item.id, title: item.title || 'Conversation',
      detail: (item.messages || []).at(-1)?.content?.slice(0, 92) || 'No messages yet', date: item.updatedAt
    })),
    ...projects.slice(0, 5).map(item => ({
      kind: 'project', id: item.id, title: item.name,
      detail: item.description || 'Project workspace', date: item.updatedAt
    }))
  ].sort((a, b) => String(b.date || '').localeCompare(String(a.date || ''))).slice(0, 5);
  const recent = $('#recentList');
  if (!items.length) {
    recent.innerHTML = '<div class="empty-inline"><span>◌</span><strong>No recent work</strong><p>Start a chat to see it here.</p></div>';
    return;
  }
  recent.innerHTML = items.map(item => `
    <div class="recent-item" role="button" tabindex="0" data-kind="${item.kind}" data-id="${escapeHtml(item.id)}">
      <span class="recent-icon">${item.kind === 'chat' ? '◌' : '▦'}</span>
      <div class="recent-copy"><strong>${escapeHtml(item.title)}</strong><p>${escapeHtml(item.detail)}</p></div>
      <time>${formatDate(item.date)}</time>
    </div>`).join('');
  recent.querySelectorAll('.recent-item').forEach(node => {
    const open = () => {
      if (node.dataset.kind === 'chat') {
        activeConversationId = node.dataset.id;
        showView('chat');
      } else {
        activeProjectId = node.dataset.id;
        showView('projects');
        renderProjectDetail();
      }
    };
    node.addEventListener('click', open);
    node.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); }
    });
  });
}

async function createConversation() {
  const record = { id: id(), title: 'New conversation', messages: [], createdAt: now(), updatedAt: now() };
  await store.put('conversations', record);
  activeConversationId = record.id;
  showView('chat');
  await refreshChats();
}

async function getActiveConversation() {
  if (!activeConversationId) return null;
  return store.get('conversations', activeConversationId);
}

async function refreshChats() {
  const chats = await store.list('conversations');
  if (activeConversationId && !chats.some(chat => chat.id === activeConversationId)) activeConversationId = null;
  if (!activeConversationId && chats.length) activeConversationId = chats[0].id;
  const query = ($('#chatSearch')?.value || '').trim().toLowerCase();
  const filtered = chats.filter(chat => String(chat.title || '').toLowerCase().includes(query));
  const list = $('#chatList');
  list.innerHTML = filtered.length ? filtered.map(chat => `
    <button type="button" data-chat-id="${escapeHtml(chat.id)}" class="${chat.id === activeConversationId ? 'active' : ''}" aria-current="${chat.id === activeConversationId ? 'true' : 'false'}">${escapeHtml(chat.title || 'Conversation')}</button>`).join('') : '<div class="sidebar-empty">No matching conversations.</div>';
  list.querySelectorAll('[data-chat-id]').forEach(button => button.addEventListener('click', async () => {
    activeConversationId = button.dataset.chatId;
    await renderConversation();
    await refreshChats();
    closeSidebar();
  }));
  await renderConversation();
}

function renderProviderResult(card) {
  const statusClass = card.text ? 'success' : 'failure';
  const title = card.isFallback ? 'OpenRouter · FALLBACK' : card.label;
  const meta = [
    card.model ? `<span>Model: ${escapeHtml(card.model)}</span>` : '',
    card.requestedModel && card.requestedModel !== card.model ? `<span>Route: ${escapeHtml(card.requestedModel)}</span>` : '',
    card.latencyMs != null ? `<span>${Number(card.latencyMs).toLocaleString()} ms</span>` : ''
  ].filter(Boolean).join('');
  return `
    <article class="provider-result ${card.isSynthesis ? 'synthesis-result' : ''}">
      <div class="provider-result-head">
        <div class="provider-result-title"><span class="provider-pill" data-provider="${escapeHtml(card.key)}">${escapeHtml(title)}</span><strong>${escapeHtml(card.status)}</strong></div>
        <span class="provider-result-status ${statusClass}">${card.text ? 'Received' : 'No output'}</span>
      </div>
      ${card.text ? `<div class="provider-result-body">${escapeHtml(card.text)}</div>` : card.error ? `<div class="provider-result-body provider-result-error">${escapeHtml(card.error)}</div>` : ''}
      ${meta ? `<div class="provider-result-meta">${meta}</div>` : ''}
    </article>`;
}

function renderMessage(message) {
  const isUser = message.role === 'user';
  const isAssistant = message.role === 'assistant';
  const meta = isUser
    ? `<div class="message-meta"><span>You · ${escapeHtml(message.routeLabel || 'Message')}</span><time>${formatDate(message.createdAt, { hour: '2-digit', minute: '2-digit' })}</time></div>`
    : `<div class="message-meta"><span>${escapeHtml(message.label || 'uneXpected')}</span><time>${formatDate(message.createdAt, { hour: '2-digit', minute: '2-digit' })}</time></div>`;
  if (isUser) return `
    <div class="message-row user-row"><div class="message-content">
      <div class="message-bubble">${escapeHtml(message.content).replace(/\n/g, '<br>')}</div>${meta}
    </div></div>`;

  const cards = Array.isArray(message.responseCards) ? message.responseCards : [];
  const fallback = message.fallback && message.fallback.attempted
    ? `<div class="fallback-notice">${message.fallback.status === 'succeeded' ? '↳ OpenRouter answered after the selected primary provider(s) failed.' : '↳ OpenRouter fallback was attempted but did not return a usable answer.'}</div>`
    : '';
  const content = cards.length
    ? fallback + cards.map(renderProviderResult).join('')
    : `<div class="message-bubble ${message.isError ? 'chat-error' : ''}">${escapeHtml(message.content || '').replace(/\n/g, '<br>')}</div>`;
  const providerMeta = message.provider
    ? `<span class="provider-pill" data-provider="${escapeHtml(message.provider)}">${escapeHtml(message.providerLabel || message.provider)}</span>`
    : '';
  return `
    <div class="message-row assistant-row"><div class="message-avatar" aria-hidden="true">u</div><div class="message-content">
      ${content}
      <div class="message-meta">${providerMeta}<span>${escapeHtml(message.label || 'uneXpected')}</span><time>${formatDate(message.createdAt, { hour: '2-digit', minute: '2-digit' })}</time></div>
    </div></div>`;
}

async function renderConversation() {
  const conversation = await getActiveConversation();
  const pane = $('#messageList');
  $('#chatHeading').textContent = conversation?.title || 'New conversation';
  if (!conversation || !conversation.messages?.length) {
    pane.innerHTML = `
      <div class="chat-welcome">
        <div class="welcome-symbol"><span>u</span><i></i></div>
        <h2>What are we working on?</h2>
        <p>Pick a model and send your first message.</p>
        <div class="prompt-suggestions">
          <button class="prompt-card" data-prompt="Help me turn an idea into a practical project plan with milestones." type="button"><span class="prompt-icon">↗</span><span><strong>Plan a project</strong></span><span class="prompt-arrow">→</span></button>
          <button class="prompt-card" data-prompt="A 24 VDC sensor is counting intermittently. Help me troubleshoot it safely, step by step." type="button"><span class="prompt-icon">⌁</span><span><strong>Troubleshoot</strong></span><span class="prompt-arrow">→</span></button>
        </div>
      </div>`;
    pane.querySelectorAll('[data-prompt]').forEach(button => button.addEventListener('click', () => {
      $('#chatInput').value = button.dataset.prompt;
      $('#chatInput').focus();
      resizeComposer();
    }));
    return;
  }
  pane.innerHTML = conversation.messages.map(renderMessage).join('');
  pane.scrollTop = pane.scrollHeight;
}

function getAgent(profileId) {
  return agents.find(agent => agent.id === profileId) || routeAgent('');
}

async function handleLocalCommand(command) {
  if (!command) return null;
  if (command.type === 'remember') {
    const timestamp = now();
    await store.put('memories', { id: id(), title: 'Saved from chat', content: command.content, source: 'explicit-chat-command', createdAt: timestamp, updatedAt: timestamp });
    await Promise.all([refreshMemories(), refreshHome()]);
    return `Saved to this device's memory:\n${command.content}`;
  }
  if (command.type === 'list-memories') {
    const memories = await store.list('memories');
    return memories.length ? `Your saved memories (${memories.length}):\n\n${memories.slice(0, 20).map((item, index) => `${index + 1}. ${item.title}: ${item.content}`).join('\n\n')}` : 'There are no saved memories on this device yet. Try: “Remember that I prefer concise reports.”';
  }
  if (command.type === 'list-projects') {
    const projects = await store.list('projects');
    return projects.length ? `Your projects (${projects.length}):\n\n${projects.map((item, index) => `${index + 1}. ${item.name}${item.description ? ` — ${item.description}` : ''} · ${(item.tasks || []).filter(task => !task.done).length} open tasks`).join('\n')}` : 'There are no projects on this device yet. Create one in Projects.';
  }
  if (command.type === 'propose-improvement') {
    const timestamp = now();
    await store.put('improvements', { id: id(), title: command.content.slice(0, 72), description: command.content, status: 'proposed', createdAt: timestamp, updatedAt: timestamp });
    await refreshImprovements();
    return `Saved your uneXpected improvement proposal locally:\n${command.content}\n\nStatus: proposed. Approval is for planning only; it does not change code or deploy anything.`;
  }
  if (command.type === 'list-improvements') {
    const items = await store.list('improvements');
    return items.length ? `Improvement proposals (${items.length}):\n\n${items.map((item, index) => `${index + 1}. [${item.status || 'proposed'}] ${item.title}: ${item.description}`).join('\n\n')}` : 'No improvement proposals have been saved yet. Try: “Improve uneXpected: add …”.';
  }
  return null;
}

function resizeComposer() {
  const field = $('#chatInput');
  if (!field) return;
  field.style.height = 'auto';
  field.style.height = `${Math.min(field.scrollHeight, 160)}px`;
}

function setRequestBusy(value) {
  requestBusy = value;
  $('#sendBtn').disabled = value;
  $('#chatInput').disabled = value;
  $('#sendBtn').innerHTML = value ? '<span>…</span>' : '<span>↑</span>';
  if (!value) $('#chatInput').disabled = false;
  $$('[data-model]').forEach(button => { button.disabled = value; });
  $('#compareBtn').disabled = value;
  if (value) $('#voiceStatus').textContent = 'Working on your request…';
}

function selectedContextRole(prompt) {
  const suggested = routeAgent(prompt, agents);
  const role = (selectedProfileId && agents.find(agent => agent.id === selectedProfileId)) || agents.find(agent => agent.id === suggested.id) || suggested;
  const skill = selectedSkillId ? skills.find(item => item.id === selectedSkillId) : null;
  return skill ? { ...role, skillInstructions: skill.instructions, skillName: skill.name } : role;
}

function responseSpeechText(payload, mode) {
  const results = payload?.results || {};
  const usable = value => typeof value === 'string' ? value.trim() : '';
  if (usable(results.synthesis?.text)) return usable(results.synthesis.text);
  if (mode === 'claude' && usable(results.anthropic?.text)) return usable(results.anthropic.text);
  if (mode === 'openai' && usable(results.openai?.text)) return usable(results.openai.text);
  if (mode === 'openrouter' && usable(results.openrouter?.text)) return usable(results.openrouter.text);
  return usable(results.openai?.text) || usable(results.anthropic?.text) || usable(results.openrouter?.text) || '';
}

async function sendChat(event) {
  event.preventDefault();
  if (requestBusy) return;
  const input = $('#chatInput');
  const prompt = input.value.trim();
  if (!prompt) return;
  let conversation = await getActiveConversation();
  if (!conversation) {
    await createConversation();
    conversation = await getActiveConversation();
  }
  if (prompt.length > MAX_USER_TASK_CHARS) {
    toast(`Please keep this request under ${MAX_USER_TASK_CHARS.toLocaleString()} characters.`);
    return;
  }

  const mode = selectedModel;
  const role = selectedContextRole(prompt);
  const skill = selectedSkillId ? skills.find(item => item.id === selectedSkillId) : null;
  $('#profileChip').textContent = skill ? `${role.id} + ${skill.id}` : role.id;
  const userMessage = {
    id: id(), role: 'user', content: prompt, createdAt: now(),
    label: 'You', routeLabel: modeLabel(mode)
  };
  conversation.messages ||= [];
  conversation.messages.push(userMessage);
  if (conversation.messages.length === 1) conversation.title = prompt.slice(0, 48) || 'New conversation';
  conversation.updatedAt = now();
  input.value = '';
  resizeComposer();
  await store.put('conversations', conversation);
  await renderConversation();
  await refreshChats();

  const localCommand = parseLocalCommand(prompt);
  if (localCommand) {
    let localResult;
    try { localResult = await handleLocalCommand(localCommand); }
    catch (error) { localResult = `The local workspace action failed: ${error.message}`; }
    conversation.messages.push({
      id: id(), role: 'assistant', content: localResult || 'That local command is not available.',
      createdAt: now(), label: 'Local tool · IndexedDB · no model call'
    });
    conversation.updatedAt = now();
    await store.put('conversations', conversation);
    await renderConversation();
    await refreshChats();
    toast(localCommand.type === 'remember' ? 'Memory saved on this device.' : localCommand.type === 'propose-improvement' ? 'Improvement idea saved locally.' : 'Local workspace information loaded.');
    await readAssistantResponse(localResult || 'Saved.');
    return;
  }

  if (mode === 'local') {
    const localResult = 'Saved on this device. General reasoning stays offline in Local tools mode. Try “Remember that…”, “What do you remember?” or “List my projects”. Choose a model route for a live response through your configured gateway.';
    conversation.messages.push({ id: id(), role: 'assistant', content: localResult, createdAt: now(), label: 'Local workspace · no model call' });
    conversation.updatedAt = now();
    await store.put('conversations', conversation);
    await renderConversation();
    await readAssistantResponse(localResult);
    return;
  }

  const assistant = {
    id: id(), role: 'assistant', content: 'Connecting to the configured gateway…',
    createdAt: now(), label: 'Request in progress', isLoading: true
  };
  conversation.messages.push(assistant);
  await store.put('conversations', conversation);
  await renderConversation();
  setRequestBusy(true);

  try {
    if (!sessionToken) throw new Error('Enter the server access token in Control center for this browser session, then retry. The token is not saved.');
    const contextConsent = $('#shareContext')?.checked === true;
    const context = contextConsent ? {
      history: conversation.messages.filter(message => message.id !== assistant.id && message.id !== userMessage.id).slice(-6),
      memories: await store.list('memories'),
      improvements: await store.list('improvements')
    } : {};
    const response = await fetch(`${gatewayBase()}/orchestrate`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', authorization: 'Bearer ' + sessionToken },
      body: JSON.stringify({ task: buildTaskEnvelope(prompt, role, context), mode: selectedModel })
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `Gateway request failed (${response.status}).`);
    const cards = collectProviderCards(payload);
    assistant.responseCards = cards;
    assistant.fallback = payload.fallback || null;
    assistant.providerSummary = cards.map(card => ({ provider: card.provider, model: card.model, requestedModel: card.requestedModel, latencyMs: card.latencyMs, fallback: card.isFallback }));
    assistant.speechText = responseSpeechText(payload, mode);
    assistant.isLoading = false;
    if (!payload.ok || !cards.some(card => Boolean(card.text))) {
      assistant.isError = true;
      assistant.content = cards.map(card => card.error).filter(Boolean).join('\n') || 'No usable model response was returned. No simulated answer was shown.';
      assistant.label = 'No verified model response';
      toast('No live model response was received.');
    } else {
      const firstSuccessful = cards.find(card => card.text);
      assistant.provider = firstSuccessful?.provider || '';
      assistant.providerLabel = firstSuccessful?.label || modeLabel(mode);
      assistant.label = cards.length > 1 ? 'Provider results · compare each answer' : `Answered by ${firstSuccessful?.label || 'the selected provider'}`;
      assistant.content = cards.map(card => card.text || card.error).filter(Boolean).join('\n\n');
    }
  } catch (error) {
    assistant.isLoading = false;
    assistant.isError = true;
    assistant.responseCards = [];
    assistant.content = `The model request did not complete.\n\n${error.message}\n\nYour original message is still saved locally. No simulated answer was shown.`;
    assistant.label = 'Connection failed · no simulated answer';
    toast('No live model response was received.');
  } finally {
    assistant.createdAt = now();
    conversation.updatedAt = now();
    await store.put('conversations', conversation);
    await renderConversation();
    await refreshChats();
    setRequestBusy(false);
    await readAssistantResponse(assistant.speechText || assistant.content);
  }
}

function updateVoiceModeButton() {
  const button = $('#voiceModeBtn');
  if (!button) return;
  button.textContent = voiceModeEnabled ? (activeRecognition || voiceBusy ? '■' : 'Resume') : '◖';
  button.title = voiceModeEnabled ? 'End voice conversation' : 'Start voice conversation';
  button.setAttribute('aria-pressed', String(voiceModeEnabled));
  button.classList.toggle('active', voiceModeEnabled);
}

function startVoiceCapture() {
  if (activeRecognition) { activeRecognition.stop(); return; }
  try {
    const language = appSettings.voiceLanguage || navigator.language || 'en-US';
    activeRecognition = createSpeechRecognition({
      environment: window,
      language,
      onStart: () => {
        $('#voiceInputBtn').textContent = '■';
        $('#voiceInputBtn').setAttribute('aria-label', 'Stop voice input');
        $('#voiceStatus').textContent = voiceModeEnabled ? `Listening · ${language}` : `Listening once · ${language}`;
        updateVoiceModeButton();
      },
      onTranscript: transcript => {
        const field = $('#chatInput');
        if (voiceModeEnabled) {
          field.value = transcript;
          voiceBusy = true;
          $('#voiceStatus').textContent = 'Thinking…';
          sendChat({ preventDefault() {} }).catch(error => {
            voiceBusy = false;
            toast(`Voice request failed: ${error.message}`);
          });
        } else {
          field.value = `${field.value.trim()}${field.value.trim() ? ' ' : ''}${transcript}`;
          field.focus();
          $('#voiceStatus').textContent = 'Voice text added · review and send';
          resizeComposer();
        }
      },
      onError: error => {
        toast(`Voice input failed: ${error}.`);
        if (voiceModeEnabled && ['not-allowed', 'service-not-allowed', 'audio-capture'].includes(error)) {
          voiceModeEnabled = false;
          voiceBusy = false;
          $('#voiceStatus').textContent = 'Microphone unavailable';
          updateVoiceModeButton();
        }
      },
      onEnd: () => {
        activeRecognition = null;
        $('#voiceInputBtn').textContent = '⌁';
        $('#voiceInputBtn').setAttribute('aria-label', 'Start voice input');
        if (!voiceModeEnabled) $('#voiceStatus').textContent = 'Saved on this device';
        else if (!voiceBusy) $('#voiceStatus').textContent = 'No speech captured · tap Resume';
        updateVoiceModeButton();
      }
    });
  } catch (error) {
    activeRecognition = null;
    if (voiceModeEnabled) { voiceModeEnabled = false; voiceBusy = false; updateVoiceModeButton(); }
    $('#voiceStatus').textContent = 'Voice input unavailable';
    toast(error.message || 'Could not start the microphone.');
  }
}

function stopVoiceConversation() {
  voiceModeEnabled = false;
  voiceBusy = false;
  activeRecognition?.stop();
  activeRecognition = null;
  window.speechSynthesis?.cancel?.();
  $('#voiceStatus').textContent = 'Voice conversation stopped';
  updateVoiceModeButton();
}

function toggleVoiceConversation() {
  if (voiceModeEnabled && (activeRecognition || voiceBusy || window.speechSynthesis?.speaking)) {
    stopVoiceConversation();
    return;
  }
  voiceModeEnabled = true;
  voiceBusy = false;
  updateVoiceModeButton();
  startVoiceCapture();
}

function speechPreferences() {
  return {
    language: appSettings.voiceLanguage || navigator.language || 'en-US',
    voiceURI: appSettings.voiceURI || '',
    rate: Number(appSettings.voiceRate || 1)
  };
}

async function readAssistantResponse(text, { force = false } = {}) {
  const shouldSpeak = force || voiceModeEnabled || appSettings.autoSpeak === true;
  if (!shouldSpeak || !String(text || '').trim()) return;
  try {
    await speakText({ environment: window, text: String(text).slice(0, 12000), ...speechPreferences() });
  } catch (error) {
    toast(error.message || 'Text-to-speech is unavailable.');
  } finally {
    if (voiceModeEnabled) {
      voiceBusy = false;
      $('#voiceStatus').textContent = 'Reply complete · listening again';
      updateVoiceModeButton();
      window.setTimeout(() => {
        if (voiceModeEnabled && !activeRecognition && !window.speechSynthesis?.speaking) startVoiceCapture();
      }, 350);
    }
  }
}

async function speakLastReply() {
  const conversation = await getActiveConversation();
  const latest = [...(conversation?.messages || [])].reverse().find(message =>
    message.role === 'assistant' && (message.speechText || message.content) && !/Connecting to the configured gateway/.test(message.content || '')
  );
  if (!latest) { toast('There is no assistant response to read aloud yet.'); return; }
  await readAssistantResponse(latest.speechText || latest.content, { force: true });
}

function renderVoiceChoices() {
  const select = $('#voiceSelect');
  if (!select) return;
  const voices = getAvailableVoices(window);
  const selected = appSettings.voiceURI || '';
  select.innerHTML = '<option value="">Device default voice</option>' + voices.map(voice =>
    `<option value="${escapeHtml(voice.voiceURI)}">${escapeHtml(voice.name)} · ${escapeHtml(voice.lang)}</option>`
  ).join('');
  select.value = voices.some(voice => voice.voiceURI === selected) ? selected : '';
}

async function saveSettingsPatch(patch) {
  const current = await store.get('settings', 'main') || { id: 'main' };
  appSettings = { ...current, ...patch, id: 'main' };
  await store.put('settings', appSettings);
  return appSettings;
}

async function refreshProjects() {
  const projects = await store.list('projects');
  const grid = $('#projectGrid');
  const empty = $('#projectEmpty');
  empty.classList.toggle('hidden', projects.length > 0);
  grid.innerHTML = projects.map(project => `
    <article class="project-card" tabindex="0" role="button" data-project-id="${escapeHtml(project.id)}">
      <div class="project-card-top"><span><i class="project-dot"></i>PROJECT</span><span>${formatDate(project.updatedAt)}</span></div>
      <h3>${escapeHtml(project.name)}</h3>
      <p>${escapeHtml(project.description || 'Project workspace')}</p>
      <div class="project-card-meta"><span>${(project.tasks || []).filter(task => !task.done).length} open tasks</span><span>Open workspace →</span></div>
    </article>`).join('');
  grid.querySelectorAll('[data-project-id]').forEach(card => {
    const open = () => { activeProjectId = card.dataset.projectId; renderProjectDetail(); };
    card.addEventListener('click', open);
    card.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); open(); } });
  });
  if (activeProjectId && !projects.some(project => project.id === activeProjectId)) activeProjectId = null;
  if (activeProjectId) await renderProjectDetail();
  else $('#projectDetail').classList.add('hidden');
}

async function renderProjectDetail() {
  const project = activeProjectId ? await store.get('projects', activeProjectId) : null;
  const detail = $('#projectDetail');
  if (!project) { detail.classList.add('hidden'); return; }
  detail.classList.remove('hidden');
  const tasks = Array.isArray(project.tasks) ? project.tasks : [];
  detail.innerHTML = `
    <div class="project-detail-head"><div><div class="eyebrow">PROJECT WORKSPACE</div><h2>${escapeHtml(project.name)}</h2><p>${escapeHtml(project.description || '')}</p></div><button class="icon-button" type="button" id="closeProjectDetail" aria-label="Close project">×</button></div>
    <div class="project-detail-tasks">${tasks.map(task => `<label class="task-row ${task.done ? 'done' : ''}"><input type="checkbox" data-task-id="${escapeHtml(task.id)}" ${task.done ? 'checked' : ''}><span>${escapeHtml(task.title || task.name || 'Task')}</span></label>`).join('') || '<p class="field-note">No tasks yet. Add the next concrete action below.</p>'}</div>
    <form class="task-add" id="taskAddForm"><input class="field" name="task" placeholder="Add a task…" aria-label="New task" required><button class="button button-primary" type="submit">Add</button></form>`;
  $('#closeProjectDetail').addEventListener('click', () => { activeProjectId = null; detail.classList.add('hidden'); });
  detail.querySelectorAll('[data-task-id]').forEach(input => input.addEventListener('change', async () => {
    const current = await store.get('projects', activeProjectId);
    const task = current.tasks.find(item => item.id === input.dataset.taskId);
    if (task) { task.done = input.checked; current.updatedAt = now(); await store.put('projects', current); await renderProjectDetail(); await refreshProjects(); }
  }));
  $('#taskAddForm').addEventListener('submit', async event => {
    event.preventDefault();
    const field = event.currentTarget.elements.task;
    const title = field.value.trim();
    if (!title) return;
    const current = await store.get('projects', activeProjectId);
    current.tasks ||= [];
    current.tasks.push({ id: id(), title, done: false });
    current.updatedAt = now();
    await store.put('projects', current);
    await renderProjectDetail();
    await refreshProjects();
    toast('Task added to project.');
  });
}

function addProject() {
  openDialog({
    title: 'Create a project', eyebrow: 'PROJECTS',
    fields: [
      { name: 'name', label: 'Project name', required: true, placeholder: 'e.g. Maintenance improvement plan' },
      { name: 'description', label: 'What is this project about?', type: 'textarea', placeholder: 'Add a short description…' }
    ],
    onSave: async values => {
      const timestamp = now();
      const project = { id: id(), name: values.name.trim(), description: values.description.trim(), tasks: [], createdAt: timestamp, updatedAt: timestamp };
      await store.put('projects', project);
      activeProjectId = project.id;
      await Promise.all([refreshProjects(), refreshHome()]);
      toast('Project created.');
    }
  });
}

async function refreshMemories() {
  const memories = await store.list('memories');
  $('#memoryEmpty').classList.toggle('hidden', memories.length > 0);
  $('#memoryList').innerHTML = memories.map(memory => `
    <article class="memory-card">
      <div class="memory-card-head"><strong>${escapeHtml(memory.title || 'Saved memory')}</strong><button type="button" data-delete-memory="${escapeHtml(memory.id)}" aria-label="Delete memory">×</button></div>
      <p>${escapeHtml(memory.content || '')}</p><time>Saved ${formatDate(memory.createdAt)}</time>
    </article>`).join('');
  $('#memoryList').querySelectorAll('[data-delete-memory]').forEach(button => button.addEventListener('click', async () => {
    if (!confirm('Delete this saved memory from this device?')) return;
    await store.remove('memories', button.dataset.deleteMemory);
    await Promise.all([refreshMemories(), refreshHome()]);
    toast('Memory deleted.');
  }));
}

function addMemory() {
  openDialog({
    title: 'Save a memory', eyebrow: 'PERSONAL KNOWLEDGE',
    fields: [
      { name: 'title', label: 'Title', required: true, placeholder: 'e.g. Preferred report format' },
      { name: 'content', label: 'What should you remember?', type: 'textarea', required: true, placeholder: 'Write the context you want to keep…' }
    ],
    onSave: async values => {
      const timestamp = now();
      await store.put('memories', { id: id(), title: values.title.trim(), content: values.content.trim(), source: 'manual', createdAt: timestamp, updatedAt: timestamp });
      await Promise.all([refreshMemories(), refreshHome()]);
      toast('Memory saved on this device.');
    }
  });
}

function renderAgents() {
  const query = ($('#agentSearch')?.value || '').trim().toLowerCase();
  const isSkills = activeProfileTab === 'skills';
  const entries = isSkills ? skills : agents;
  $('#agentCount').textContent = isSkills ? `${skills.length} skills` : `${agents.length} profiles`;
  $('#showAgentsBtn').classList.toggle('active', !isSkills);
  $('#showSkillsBtn').classList.toggle('active', isSkills);
  const grid = $('#agentGrid');
  const filtered = entries.filter(item => `${item.id} ${item.name || ''} ${item.description || ''} ${item.responsibility || ''}`.toLowerCase().includes(query));
  grid.innerHTML = filtered.map(item => `
    <article class="agent-card">
      <div><strong>${escapeHtml(item.name || item.id)}</strong><p>${escapeHtml(item.description || item.responsibility || '')}</p><small>${escapeHtml(item.status || item.type || 'Workflow reference')}</small></div>
      <button type="button" data-profile-id="${escapeHtml(item.id)}" data-profile-kind="${isSkills ? 'skill' : 'agent'}">Use this ${isSkills ? 'skill' : 'profile'} ↗</button>
    </article>`).join('') || '<div class="empty-inline"><strong>No matching profiles</strong><p>Try another search term.</p></div>';
  grid.querySelectorAll('[data-profile-id]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.profileKind === 'skill') selectedSkillId = button.dataset.profileId;
    else selectedProfileId = button.dataset.profileId;
    $('#profileChip').textContent = button.dataset.profileKind === 'skill'
      ? `${getAgent(selectedProfileId || 'orchestrator').id} + ${selectedSkillId}`
      : selectedProfileId;
    showView('chat');
    toast(`${button.dataset.profileKind === 'skill' ? 'Skill' : 'Profile'} selected for your next request.`);
  }));
}

async function refreshImprovements() {
  const items = await store.list('improvements');
  const list = $('#improvementList');
  const empty = $('#improvementEmpty');
  empty.classList.toggle('hidden', items.length > 0);
  list.innerHTML = items.map(item => `
    <article class="improvement-card">
      <div class="improvement-card-head"><strong>${escapeHtml(item.title || 'Improvement proposal')}</strong><span class="improvement-state">${escapeHtml((item.status || 'proposed').replaceAll('-', ' '))}</span></div>
      <p>${escapeHtml(item.description || '')}</p>
      ${item.expectedOutcome ? `<small>Outcome: ${escapeHtml(item.expectedOutcome)}</small>` : ''}
      <div class="improvement-actions">${item.status === 'proposed' ? `<button type="button" data-approve-improvement="${escapeHtml(item.id)}">Approve for planning</button>` : ''}<button type="button" data-defer-improvement="${escapeHtml(item.id)}">Defer</button></div>
    </article>`).join('');
  list.querySelectorAll('[data-approve-improvement]').forEach(button => button.addEventListener('click', async () => {
    const item = await store.get('improvements', button.dataset.approveImprovement);
    if (!item) return;
    item.status = 'approved-for-planning'; item.updatedAt = now();
    await store.put('improvements', item); await refreshImprovements();
    toast('Approved for planning. No code or deployment has changed.');
  }));
  list.querySelectorAll('[data-defer-improvement]').forEach(button => button.addEventListener('click', async () => {
    const item = await store.get('improvements', button.dataset.deferImprovement);
    if (!item) return;
    item.status = 'deferred'; item.updatedAt = now();
    await store.put('improvements', item); await refreshImprovements();
    toast('Improvement proposal deferred.');
  }));
}

function addImprovement() {
  openDialog({
    title: 'Propose an uneXpected improvement', eyebrow: 'CONTINUOUS IMPROVEMENT',
    fields: [
      { name: 'title', label: 'Improvement idea', required: true, placeholder: 'e.g. Arabic voice controls' },
      { name: 'description', label: 'What should change?', type: 'textarea', required: true, placeholder: 'Describe the behavior you want…' },
      { name: 'expectedOutcome', label: 'How will we know it improved?', placeholder: 'e.g. 3 supported languages tested on Android' }
    ],
    onSave: async values => {
      const timestamp = now();
      await store.put('improvements', { id: id(), title: values.title.trim(), description: values.description.trim(), expectedOutcome: values.expectedOutcome.trim(), status: 'proposed', createdAt: timestamp, updatedAt: timestamp });
      await refreshImprovements();
      toast('Improvement proposal saved locally.');
    }
  });
}

async function saveGatewayUrl() {
  const gatewayUrl = $('#gatewayUrl').value.trim();
  await saveSettingsPatch({ gatewayUrl });
}

async function checkGateway() {
  await saveGatewayUrl();
  const box = $('#gatewayDetails');
  box.classList.remove('hidden');
  box.textContent = 'Checking the health endpoint…';
  try {
    const response = await fetch(`${gatewayBase()}/health`, { cache: 'no-store' });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`Health endpoint returned HTTP ${response.status}.`);
    if (!data.providers) {
      box.textContent = `HTTP ${response.status} · ${data.service || 'Local preview'}\nThis service is not connected to the model gateway.`;
      $('#gatewayStatus').textContent = 'Local preview only';
      setConnection('On this device', 'local');
      return;
    }
    const names = [['openai', 'ChatGPT'], ['anthropic', 'Claude'], ['openrouter', 'OpenRouter']];
    const lines = names.map(([key, label]) => {
      const provider = data.providers?.[key];
      return `${label}: ${provider?.configured ? 'configured' : 'not configured'} · ${provider?.verified ? 'verified' : 'not yet verified'} · ${provider?.model || 'model not reported'}`;
    });
    box.textContent = `HTTP ${response.status} · ${data.service || 'uneXpected gateway'}\nAuthentication: ${data.authConfigured ? 'configured' : 'not configured'}\n\n${lines.join('\n')}\n\nConfigured does not mean verified. Use the real test for a provider check.`;
    $('#gatewayStatus').textContent = 'Reachable';
    $('#providerHealthList').innerHTML = lines.map(line => `<span>${escapeHtml(line)}</span>`).join('');
    setConnection('Gateway reachable', 'online');
  } catch (error) {
    box.textContent = `Gateway check failed: ${error.message}\nLocal projects, conversations and memory remain available.`;
    $('#gatewayStatus').textContent = 'Unavailable';
    setConnection('On this device', 'warning');
  }
}

async function testProvider() {
  await saveGatewayUrl();
  const box = $('#gatewayDetails');
  box.classList.remove('hidden');
  if (!sessionToken) {
    box.textContent = 'Enter the server access token above, then run the test again. It is not saved.';
    $('#accessToken').focus();
    return;
  }
  const provider = $('#testProviderSelect').value;
  const providerName = provider === 'anthropic' ? 'Claude' : provider === 'openrouter' ? 'OpenRouter' : 'ChatGPT';
  box.textContent = `Sending one real ${providerName} test request…`;
  try {
    const response = await fetch(`${gatewayBase()}/test-provider`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'authorization': 'Bearer ' + sessionToken },
      body: JSON.stringify({ provider })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || `Provider test failed (${response.status}).`);
    box.textContent = `LIVE · verified response\nProvider: ${data.provider}\nActual model: ${data.model}\nLatency: ${data.latencyMs} ms\n\n${data.text || ''}`;
    toast(`${providerName} returned a real test response.`);
  } catch (error) {
    box.textContent = `Provider test failed: ${error.message}\nNo simulated response was shown.`;
    toast(`${providerName} test failed.`);
  }
}

async function refreshSettings() {
  const saved = await store.get('settings', 'main') || { id: 'main' };
  appSettings = defaultAppSettings(saved, navigator.language);
  $('#gatewayUrl').value = appSettings.gatewayUrl || '';
  $('#voiceLanguage').value = appSettings.voiceLanguage || 'en-US';
  $('#voiceRate').value = String(appSettings.voiceRate || 1);
  $('#voiceRateLabel').textContent = `${Number(appSettings.voiceRate || 1).toFixed(1)}×`;
  $('#autoSpeakToggle').checked = appSettings.autoSpeak === true;
  renderVoiceChoices();
  $('#storageState').textContent = store ? 'Available · IndexedDB' : 'Unavailable';
  const persistence = await navigator.storage?.persisted?.().catch(() => false);
  $('#persistState').textContent = persistence ? 'Granted' : 'Not confirmed';
  await refreshImprovements();
}

async function exportBackup() {
  const data = await store.exportAll();
  const payload = createBackupPayload(data);
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `unexpected-workspace-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
  toast('Workspace backup exported. Access token is not included.');
}

async function importBackup(file) {
  if (!file) return;
  try {
    const payload = JSON.parse(await file.text());
    const data = parseBackupPayload(payload);
    if (!confirm('Restore this backup? Existing local workspace records will be replaced.')) return;
    await store.importAll(data);
    activeConversationId = null;
    activeProjectId = null;
    appSettings = defaultAppSettings(await store.get('settings', 'main'), navigator.language);
    $('#gatewayUrl').value = appSettings.gatewayUrl || '';
    await Promise.all([refreshHome(), refreshChats(), refreshProjects(), refreshMemories(), refreshSettings()]);
    toast('Backup restored to this device. The server access token was not restored.');
  } catch (error) {
    toast(error.message || 'Could not restore backup.');
  } finally {
    $('#importFile').value = '';
  }
}

async function clearAllData() {
  if (!confirm('Permanently delete all uneXpected projects, conversations and memories stored in this browser?')) return;
  if (!confirm('Confirm once more: delete all local workspace data on this device?')) return;
  await store.clearAll();
  activeConversationId = null;
  activeProjectId = null;
  await Promise.all([refreshHome(), refreshChats(), refreshProjects(), refreshMemories(), refreshSettings()]);
  toast('Local workspace data deleted.');
}

function updateProfileChip() {
  const role = selectedProfileId ? agents.find(agent => agent.id === selectedProfileId) : null;
  const skill = selectedSkillId ? skills.find(item => item.id === selectedSkillId) : null;
  $('#profileChip').textContent = skill ? `${role?.id || 'orchestrator'} + ${skill.id}` : role?.id || 'auto-route';
}

function bindEvents() {
  $('#sidebarToggle').addEventListener('click', () => toggleSidebar());
  $('#sidebarClose').addEventListener('click', closeSidebar);
  $('#sidebarBackdrop').addEventListener('click', closeSidebar);
  $('#sidebar').addEventListener('keydown', event => {
    if (event.key !== 'Tab' || !isMobileNavigation() || !$('#sidebar').classList.contains('open')) return;
    const tabbable = [...$('#sidebar').querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')];
    if (!tabbable.length) { event.preventDefault(); $('#sidebarClose').focus(); return; }
    const first = tabbable[0];
    const last = tabbable[tabbable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  window.addEventListener('resize', syncSidebarForViewport);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeSidebar();
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      createConversation();
    }
  });
  $$('.nav-item').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
  $$('[data-go]').forEach(button => button.addEventListener('click', () => showView(button.dataset.go)));
  $('#avatarBtn').addEventListener('click', () => showView('settings'));
  $('#mobileConnection').addEventListener('click', () => showView('settings'));
  $('#newChatBtn').addEventListener('click', createConversation);
  $('#deleteChatBtn').addEventListener('click', async () => {
    const chat = await getActiveConversation();
    if (!chat) return;
    if (!confirm('Delete this conversation from this device?')) return;
    await store.remove('conversations', chat.id);
    activeConversationId = null;
    await refreshChats();
    toast('Conversation deleted.');
  });
  $('#chatForm').addEventListener('submit', sendChat);
  $('#chatInput').addEventListener('input', resizeComposer);
  $('#chatSearch').addEventListener('input', refreshChats);
  $$('[data-model]').forEach(button => button.addEventListener('click', () => setSelectedModel(button.dataset.model)));
  $('#compareBtn').addEventListener('click', () => setSelectedModel(selectedModel === 'both' ? 'openai' : 'both'));
  $('#localModeBtn').addEventListener('click', () => setSelectedModel(selectedModel === 'local' ? 'openai' : 'local'));
  $('#modelMode').addEventListener('change', event => setSelectedModel(event.target.value));
  $('#voiceInputBtn').addEventListener('click', startVoiceCapture);
  $('#voiceModeBtn').addEventListener('click', toggleVoiceConversation);
  $('#speakLastBtn').addEventListener('click', speakLastReply);
  $('#stopVoiceBtn').addEventListener('click', () => { window.speechSynthesis?.cancel?.(); toast('Speech stopped.'); });
  $('#testVoiceBtn').addEventListener('click', () => readAssistantResponse('Hello. I am uneXpected. We can work together by voice. Your workspace stays local unless you choose to share context.', { force: true }));
  $('#voiceLanguage').addEventListener('change', event => saveSettingsPatch({ voiceLanguage: event.target.value }));
  $('#voiceSelect').addEventListener('change', event => saveSettingsPatch({ voiceURI: event.target.value }));
  $('#voiceRate').addEventListener('input', event => {
    const rate = Number(event.target.value);
    $('#voiceRateLabel').textContent = `${rate.toFixed(1)}×`;
    saveSettingsPatch({ voiceRate: rate });
  });
  $('#autoSpeakToggle').addEventListener('change', event => saveSettingsPatch({ autoSpeak: event.target.checked }));
  $('#addProjectBtn').addEventListener('click', addProject);
  $('#emptyProjectBtn').addEventListener('click', addProject);
  $('#addMemoryBtn').addEventListener('click', addMemory);
  $('#agentSearch').addEventListener('input', renderAgents);
  $('#showAgentsBtn').addEventListener('click', () => { activeProfileTab = 'agents'; $('#agentSearch').value = ''; renderAgents(); });
  $('#showSkillsBtn').addEventListener('click', () => { activeProfileTab = 'skills'; $('#agentSearch').value = ''; renderAgents(); });
  $('#gatewayUrl').addEventListener('change', saveGatewayUrl);
  $('#accessToken').addEventListener('input', event => {sessionToken=event.target.value.trim();});
  $('#checkGatewayBtn').addEventListener('click', checkGateway);
  $('#testProviderBtn').addEventListener('click', testProvider);
  $('#exportBtn').addEventListener('click', exportBackup);
  $('#importBtn').addEventListener('click', () => $('#importFile').click());
  $('#importFile').addEventListener('change', event => importBackup(event.target.files[0]));
  $('#clearDataBtn').addEventListener('click', clearAllData);
  $('#addImprovementBtn').addEventListener('click', addImprovement);
  $('#dialogCloseBtn').addEventListener('click', () => $('#simpleDialog').close());
  $('#dialogCancelBtn').addEventListener('click', () => $('#simpleDialog').close());
}

async function boot() {
  const database = await openDatabase();
  store = new LocalStore(database);
  const [agentData, settings] = await Promise.all([
    Promise.all([
      fetch('./agents.json').then(response => { if (!response.ok) throw new Error('Could not load profile index.'); return response.json(); }),
      fetch('./skills.json').then(response => { if (!response.ok) throw new Error('Could not load skill index.'); return response.json(); })
    ]),
    store.get('settings', 'main')
  ]);
  agents = agentData[0].agents || [];
  skills = agentData[1].skills || [];
  appSettings = defaultAppSettings(settings, navigator.language);
  if (!settings) await store.put('settings', appSettings);
  $('#todayLabel').textContent = new Intl.DateTimeFormat(undefined, { weekday: 'short', month: 'short', day: 'numeric' }).format(new Date());
  syncSidebarForViewport();
  bindEvents();
  setSelectedModel('openai');
  updateProfileChip();
  if (window.speechSynthesis) window.speechSynthesis.onvoiceschanged = renderVoiceChoices;
  renderVoiceChoices();
  await Promise.all([refreshHome(), refreshChats(), refreshProjects(), refreshMemories(), refreshSettings()]);
  renderAgents();
  if ('serviceWorker' in navigator && location.protocol === 'https:') {
    navigator.serviceWorker.register('./sw.js')
      .then(() => setConnection('Offline shell ready', 'online', 'App shell cached on this device'))
      .catch(() => setConnection('On this device', 'local'));
  }
  fetch(`${location.origin}/health`, { cache: 'no-store' })
    .then(response => response.json())
    .then(data => {
      if (data.providers) {
        setConnection('Gateway reachable', 'online');
        const names = [['openai', 'ChatGPT'], ['anthropic', 'Claude'], ['openrouter', 'OpenRouter']];
        $('#providerHealthList').innerHTML = names.map(([key, label]) => `<span>${label} · ${data.providers?.[key]?.configured ? 'configured' : 'not configured'}</span>`).join('');
      } else setConnection('On this device', 'local');
    })
    .catch(() => setConnection('On this device', 'local'));
  requestPersistentStorage().then(result => {
    if (result.granted) $('#persistState').textContent = 'Granted';
  }).catch(() => {});
}

window.addEventListener('beforeinstallprompt', event => {
  event.preventDefault();
  installPrompt = event;
  $('#installBtn').classList.remove('hidden');
});
$('#installBtn').addEventListener('click', async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  $('#installBtn').classList.add('hidden');
});
window.addEventListener('appinstalled', () => toast('uneXpected was installed on this device.'));
boot().catch(error => {
  console.error(error);
  $('#mainContent').innerHTML = `<section class="settings-section"><h2>Workspace could not start</h2><p>${escapeHtml(error.message)}</p><p class="field-note">Open uneXpected through its HTTPS address after the phone app assets have been deployed. Browser file mode does not support the installable offline shell.</p></section>`;
});
