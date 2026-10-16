'use strict';
const $ = (s, root = document) => root.querySelector(s);
const esc = (value) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]
  );
const paths = {
  home: 'M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z',
  device: 'M6 2h12v20H6zM10 18h4',
  agent:
    'M7 10a5 5 0 0 1 10 0v3a5 5 0 0 1-10 0zM5 9H3v6h2m14-6h2v6h-2M9 9h.01M15 9h.01M9 20h6M12 2v3',
  model: 'm12 2 9 5v10l-9 5-9-5V7zm0 0v20M3 7l9 5 9-5M3 17l9-5 9 5',
  chat: 'M21 12a9 9 0 0 1-9 9H3l2-5A9 9 0 1 1 21 12ZM8 10h8m-8 4h5',
  history: 'M3 12a9 9 0 1 0 3-7L3 8m0-6v6h6m3-1v6l4 2',
  plus: 'M12 5v14M5 12h14',
  arrow: 'M5 12h14m-5-5 5 5-5 5',
  wave: 'M3 10v4m4-8v12m5-16v20m5-16v12m4-8v4',
  check: 'm5 12 4 4L19 6',
  copy: 'M9 9h12v12H9zM5 15H3V3h12v2',
  gear: 'M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8Zm0-6v3m0 14v3M2 12h3m14 0h3M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2',
};
const icon = (name) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name] || paths.wave}"/></svg>`;
const state = {
  page: 'home',
  user: null,
  voices: {},
  overview: null,
  history: [],
  chat: [],
  session: null,
  chatAgent: null,
  sending: false,
  modelDirty: false,
};
const pages = {
  home: ['工作台', 'OVERVIEW'],
  devices: ['我的设备', 'DEVICES'],
  agents: ['角色与声音', 'COMPANIONS'],
  model: ['模型接入', 'MODEL CONNECTION'],
  chat: ['对话测试', 'PLAYGROUND'],
  history: ['对话记录', 'CONVERSATIONS'],
};
let toastTimer;
function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 4200);
}
async function api(path, options = {}) {
  const response = await fetch('/api' + path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  });
  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error('服务响应异常，请稍后重试');
  }
  if (!response.ok) {
    if (response.status === 401 && state.user) {
      state.user = null;
      await boot();
    }
    throw new Error(data.error || '操作失败');
  }
  return data;
}
const body = (method, data) => ({ method, body: JSON.stringify(data) });
const button = (label, action, style = '', glyph = '') =>
  `<button class="button ${style}" data-action="${action}">${glyph ? icon(glyph) : ''}${label}</button>`;
const brand = () =>
  `<div class="brand"><div class="brand-symbol"><i></i><i></i><i></i></div><div><strong>声伴</strong><small>VOICE STUDIO</small></div></div>`;
const date = (timestamp) =>
  timestamp
    ? new Date(timestamp < 1e11 ? timestamp * 1000 : timestamp).toLocaleString('zh-CN', {
        timeZone: 'Asia/Shanghai',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    : '尚未连接';
const badge = (online) =>
  `<span class="badge ${online ? 'online' : ''}"><i class="dot" ${online ? '' : 'hidden'}></i>${online ? '在线' : '待接入'}</span>`;
const agentOptions = (selected) =>
  state.overview.agents
    .map(
      (a) =>
        `<option value="${esc(a.id)}" ${a.id === selected ? 'selected' : ''}>${esc(a.name)}</option>`
    )
    .join('');
const field = (label, name, value = '', type = 'text', hint = '', full = false, attrs = '') =>
  `<div class="field ${full ? 'full' : ''}"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}" value="${esc(value)}" ${attrs}>${hint ? `<small>${hint}</small>` : ''}</div>`;
const empty = (title, description, action = '', label = '') =>
  `<div class="empty">${icon('wave')}<h3>${title}</h3><p>${description}</p>${action ? button(label, action, 'secondary', 'plus') : ''}</div>`;
function boardArt() {
  return `<svg class="device-illustration" viewBox="0 0 220 200" aria-hidden="true"><rect x="31" y="20" width="158" height="161" rx="25" fill="#b0bba0"/><rect x="25" y="15" width="158" height="161" rx="25" fill="#d0d6bc" stroke="#bcc5a9"/><rect x="37" y="28" width="134" height="104" rx="13" fill="#273e32"/><rect x="42" y="33" width="124" height="94" rx="10" fill="#314b3c"/><g stroke="#b4c392" stroke-width="4" stroke-linecap="round"><path d="M71 73v13m12-25v37m12-50v63m12-44v25m12-34v43m12-24v5"/></g><circle cx="66" cy="153" r="4" fill="#8a9977"/><g stroke="#99a588" stroke-width="2" stroke-linecap="round"><path d="M86 146h49m-49 6h49m-49 6h49"/></g><circle cx="153" cy="153" r="5" fill="#d4855d"/><path d="M89 176h30v5H89z" fill="#8b967b"/></svg>`;
}
async function boot() {
  try {
    const info = await api('/bootstrap');
    state.voices = info.voices;
    state.user = info.user;
    if (!info.user) {
      renderAuth(info.needs_setup);
      return;
    }
    await refresh();
    renderShell();
  } catch (error) {
    $('#app').innerHTML =
      `<div class="loading">${esc(error.message)}<br><button class="button secondary" data-action="retry">重新连接</button></div>`;
  }
}
function renderAuth(setup) {
  $('#app').innerHTML =
    `<div class="auth-shell"><section class="auth-story">${brand()}<div class="eyebrow">A LITTLE DEVICE. A LITTLE CLOSER.</div><h1>让每一句话，<br>都有回应。</h1><p>属于你自己的语音伙伴。<br>从一个声音开始，把角色、模型与设备连接起来。</p><div class="auth-wave">${Array.from({ length: 15 }, () => '<i></i>').join('')}</div><div class="version">ESP32 SERVER / PERSONAL EDITION</div></section><section class="auth-form"><form id="auth-form" data-setup="${setup}"><div class="eyebrow">YOUR PRIVATE SPACE</div><h2>${setup ? '创建你的控制台' : '欢迎回来'}</h2><p>${setup ? '首次使用，设置一个管理员账号。' : '登录后，继续照顾你的语音伙伴。'}</p>${field('管理员账号', 'username', '', 'text', '', false, 'required minlength="3" maxlength="64" autocomplete="username"')}${field('密码', 'password', '', 'password', '至少 12 个字符', false, `required minlength="12" maxlength="256" autocomplete="${setup ? 'new-password' : 'current-password'}"`)}<button class="button" type="submit">${setup ? '创建账号并进入' : '进入控制台'}${icon('arrow')}</button><div class="error-text" id="auth-error" role="alert"></div><p class="auth-foot">独立账号 · 本机数据 · 自由选择模型</p></form></section></div>`;
}
async function refresh() {
  state.overview = await api('/overview');
  if (!state.chatAgent) state.chatAgent = state.overview.agents[0]?.id;
}
function renderShell() {
  const [name] = pages[state.page];
  $('#app').innerHTML =
    `<div class="shell"><aside class="sidebar">${brand()}<div class="nav-caption">YOUR WORKSPACE</div><nav>${Object.entries(
      pages
    )
      .map(
        ([key, [title]]) =>
          `<a href="#${key}" class="nav-link ${state.page === key ? 'active' : ''}" data-page="${key}">${icon(key === 'devices' ? 'device' : key === 'agents' ? 'agent' : key)}${title}</a>`
      )
      .join(
        ''
      )}</nav><div class="sidebar-foot"><div class="private-tag"><i class="dot"></i>个人控制台</div><p>一个声音，一个自己的小世界。</p></div></aside><div class="workspace"><header class="topbar"><div class="breadcrumb">我的空间<span>/</span><strong>${name}</strong></div><div class="account"><span class="badge online">独立部署</span><span class="avatar">${esc(state.user.username.slice(0, 2).toUpperCase())}</span><button data-action="logout">退出</button></div></header><main id="content" class="content"></main></div></div>`;
  renderPage();
}
function heading(subtitle, action = '') {
  const [name, en] = pages[state.page];
  return `<div class="page-heading"><div><div class="eyebrow">${en}</div><h1>${name}</h1><p>${subtitle}</p></div>${action}</div>`;
}
function deviceCard(device, full = false) {
  return `<div class="${full ? 'panel device-full' : ''}"><div class="device-card"><div class="device-tile">${icon('device')}</div><div class="device-main"><h3>${esc(device.name)}</h3><p class="mono">${esc(device.mac)}</p><p>${esc(device.agent_name)}</p></div>${badge(device.online)}</div>${full ? `<div class="status-line"><span>最近连接</span><span>${date(device.last_seen)}</span></div><div class="card-actions"><button class="button secondary tiny" data-edit-device="${esc(device.mac)}">编辑设备</button><button class="button secondary tiny" data-connection="${esc(device.mac)}">${icon('copy')}接入地址</button></div>` : ''}</div>`;
}
function renderPage() {
  const o = state.overview;
  let html = '';
  if (state.page === 'home') {
    html =
      heading(
        '你的设备、声音和日常，都在这里。',
        button('刷新状态', 'refresh', 'secondary', 'history')
      ) +
      `<section class="hero"><div class="hero-copy"><div class="eyebrow">MAKE ROOM FOR A VOICE</div><h2>把声音，变成陪伴。</h2><p>给小小的设备一个性格，让每一次唤醒，<br>都成为一次自然的对话。</p>${button('和它聊一会儿', 'open-chat', 'warm', 'chat')}</div><div class="hero-art">${boardArt()}<div class="device-note">ESP32-S3 / VOICE COMPANION</div></div></section><div class="metric-row"><div class="metric"><div class="metric-title">已添加设备${icon('device')}</div><div class="metric-value">${o.devices.length}<small>台设备</small></div></div><div class="metric"><div class="metric-title">当前在线${icon('wave')}</div><div class="metric-value">${o.devices.filter((d) => d.online).length}<small>台设备</small></div></div><div class="metric"><div class="metric-title">我的角色${icon('agent')}</div><div class="metric-value">${o.agents.length}<small>个伙伴</small></div></div><div class="metric"><div class="metric-title">对话记录${icon('chat')}</div><div class="metric-value">${o.messages}<small>条消息</small></div></div></div><div class="dashboard-grid"><section class="panel"><div class="section-heading"><h2>我的设备</h2><button class="text-button" data-page="devices">查看全部 ↗</button></div>${
        o.devices.length
          ? o.devices
              .slice(0, 2)
              .map((d) => deviceCard(d))
              .join('')
          : empty('给声音一个家', '添加你的 ESP32 设备，开始建立连接。', 'add-device', '添加设备')
      }<div class="status-line"><span>${o.engine_online ? '语音引擎已就绪' : '语音引擎尚未就绪'}</span><span class="badge ${o.engine_online ? 'online' : ''}">${o.engine_online ? '运行中' : '等待启动'}</span></div></section><section class="panel"><div class="section-heading"><h2>声音如何相遇</h2><span>VOICE PIPELINE</span></div><div class="pipeline"><div class="pipeline-step"><span class="step-num">01</span><div><strong>听见你</strong><small>SenseVoice · 中文语音识别</small></div><span class="step-tag">ASR</span></div><div class="pipeline-step"><span class="step-num">02</span><div><strong>理解你</strong><small>${esc(o.model.model)}</small></div><span class="step-tag">LLM</span></div><div class="pipeline-step"><span class="step-num">03</span><div><strong>回应你</strong><small>Edge TTS · 自然中文声音</small></div><span class="step-tag">TTS</span></div></div></section></div>${networkNotice()}<div class="footer-note"><span>VOICE STUDIO / BUILT FOR YOUR EVERYDAY</span><span>先让对话发生，再慢慢探索。</span></div>`;
  } else if (state.page === 'devices') {
    html =
      heading(
        '管理设备与角色的连接。设备成功接入后会显示在线。',
        button('添加设备', 'add-device', '', 'plus')
      ) +
      (o.devices.length
        ? `<div class="card-grid">${o.devices.map((d) => deviceCard(d, true)).join('')}</div>`
        : `<section class="panel">${empty('第一位伙伴，等你连接', '添加设备的 MAC 地址，并为它选择一个角色。', 'add-device', '添加设备')}</section>`) +
      networkNotice();
  } else if (state.page === 'agents') {
    html =
      heading('声音是它的外表，角色是它的性格。', button('新建角色', 'add-agent', '', 'plus')) +
      `<div class="card-grid">${o.agents.map((a) => `<section class="panel agent-card"><div class="agent-avatar">${icon('agent')}</div><h3>${esc(a.name)}</h3><p>${esc(a.prompt)}</p><div class="agent-meta"><span>${esc(state.voices[a.voice] || a.voice)}</span><span>语速 ${a.rate > 0 ? '+' : ''}${a.rate}%</span></div><div class="card-actions"><button class="button secondary tiny" data-edit-agent="${esc(a.id)}">${icon('gear')}配置角色</button></div></section>`).join('')}</div>`;
  } else if (state.page === 'model') {
    const m = o.model;
    state.modelDirty = false;
    html =
      heading('连接本地模型，或使用兼容 Chat Completions 的模型服务。') +
      `<section class="panel form-panel"><div class="model-intro"><div class="model-logo">${icon('model')}</div><div><h2>对话的思考引擎</h2><p>网页测试与板子对话共用这份模型配置。</p></div></div><form id="model-form"><div class="form-grid"><div class="field"><label for="provider">接入方式</label><select id="provider" name="provider"><option value="ollama" ${m.provider === 'ollama' ? 'selected' : ''}>Ollama · 本地模型</option><option value="openai" ${m.provider === 'openai' ? 'selected' : ''}>兼容 API · 云端模型</option></select></div>${field('模型名称', 'model', m.model, 'text', '例如 qwen2.5:3b', false, 'required maxlength="150"')}${field('API 地址', 'base_url', m.base_url, 'url', '填写 API 基础地址，通常以 /v1 结尾', true, 'required')}${field('API Key', 'api_key', '', 'password', m.has_api_key ? '已有密钥；地址不变时留空会保留原密钥' : '本地 Ollama 可留空', true, 'autocomplete="new-password"')}${field('温度', 'temperature', m.temperature, 'number', '越低越稳定，越高越多样', false, 'min="0" max="2" step="0.1" required')}${field('回复长度上限', 'max_tokens', m.max_tokens, 'number', '语音对话建议保持简短', false, 'min="32" max="8192" required')}</div><div class="form-actions"><span class="form-note">密钥仅保存在本机，不会回显。</span><button type="button" class="button secondary" data-action="test-model">测试连接</button><button class="button" type="submit">保存配置</button></div></form><div id="test-result" class="test-result" role="status"></div></section>`;
  } else if (state.page === 'chat') {
    html =
      heading('在网页里试试角色与模型。这里进行文字对话，不使用麦克风。') +
      `<div class="chat-layout"><section class="panel chat-panel"><div class="chat-top"><div class="field"><select id="chat-agent" aria-label="选择测试角色" ${state.sending ? 'disabled' : ''}>${agentOptions(state.chatAgent)}</select></div><button class="text-button" data-action="new-chat" ${state.sending ? 'disabled' : ''}>新会话 ↗</button></div><div class="chat-messages" id="chat-messages">${state.chat.length ? state.chat.map((m) => `<div class="bubble ${m.role === 'user' ? 'user' : ''}">${esc(m.content)}</div>`).join('') : `<div class="chat-start"><div class="agent-avatar">${icon('wave')}</div><h3>从一句“你好”开始。</h3><p>试试语气，聊聊想法，找到你喜欢的相处方式。</p></div>`}${state.sending ? '<div class="bubble">正在想怎么回答你…</div>' : ''}</div><form id="chat-form" class="chat-compose"><textarea id="chat-input" name="text" rows="1" maxlength="2000" placeholder="想和它说些什么？" aria-label="对话内容" required ${state.sending ? 'disabled' : ''}></textarea><button class="button" type="submit" ${state.sending ? 'disabled' : ''}>发送${icon('arrow')}</button></form></section><aside class="panel chat-side"><h3>这次对话</h3><p>模型<br><strong>${esc(o.model.model)}</strong></p><div class="separator"></div><p>角色配置会影响对话语气。<br>想换一种相处方式，可以去“角色与声音”调整提示词。</p><div class="separator"></div><p>测试记录会保存在本机。<br>“新会话”会清空当前上下文，历史记录仍然保留。</p></aside></div>`;
  } else if (state.page === 'history') {
    html =
      heading(
        '设备语音与网页测试的文字记录，保存在你的本机。',
        button('刷新记录', 'refresh', 'secondary', 'history')
      ) +
      `<section class="panel history-wrap">${state.history.length ? `<table class="history-table"><thead><tr><th>时间</th><th>说话人</th><th>内容</th><th>来源 / 角色</th></tr></thead><tbody>${state.history.map((m) => `<tr><td class="mono">${date(m.created_at)}</td><td><span class="badge ${m.role === 'assistant' ? 'online' : ''}">${{ user: '你', assistant: '伙伴', tool: '工具' }[m.role] || esc(m.role)}</span></td><td class="message">${esc(m.content)}</td><td>${esc(m.device_name || '网页测试')}<br>${esc(m.agent_name)}</td></tr>`).join('')}</tbody></table>` : empty('故事还没开始', '成功的网页对话和设备语音对话，会在这里留下记录。')}</section><p class="form-note">显示最近 100 条消息。首版保存文字，不保存原始录音。</p>`;
  }
  $('#content').innerHTML = html;
  if (state.page === 'chat') {
    const el = $('#chat-messages');
    el.scrollTop = el.scrollHeight;
  }
}
function networkNotice() {
  const local = ['127.0.0.1', 'localhost'].includes(new URL(state.overview.public_url).hostname);
  return local
    ? `<div class="notice"><b>接入提示</b>　当前后台只在独立部署，可以先测试角色和模型。板子接入需要能访问这台电脑；目前手机热点与电脑有线网络尚未互通。</div>`
    : '';
}
async function navigate(page) {
  if (!pages[page]) return;
  state.page = page;
  await refresh();
  if (page === 'history') state.history = await api('/history');
  renderShell();
  history.replaceState(null, '', '#' + page);
}
function modal(title, contents) {
  const el = $('#dialog');
  el.innerHTML = `<div class="modal-head"><h2>${title}</h2><button class="close-button" data-action="close-modal" aria-label="关闭弹窗">×</button></div><div class="modal-body">${contents}</div>`;
  el.showModal();
}
function agentModal(agent) {
  const a = agent || {
    name: '',
    prompt: '你是一个温和、自然的中文聊天伙伴。回答简短，适合语音朗读。',
    voice: 'zh-CN-XiaoxiaoNeural',
    rate: 0,
  };
  modal(
    agent ? '配置角色' : '新建角色',
    `<form id="agent-form" data-id="${esc(agent?.id || '')}"><div class="form-grid">${field('角色名称', 'name', a.name, 'text', '', true, 'required maxlength="80"')}<div class="field full"><label for="prompt">角色介绍与说话方式</label><textarea id="prompt" name="prompt" rows="7" required maxlength="8000">${esc(a.prompt)}</textarea><small>描述它的性格、回答长度，以及你希望它如何与你相处。</small></div><div class="field"><label for="voice">中文音色</label><select id="voice" name="voice">${Object.entries(
      state.voices
    )
      .map(
        ([id, name]) => `<option value="${id}" ${a.voice === id ? 'selected' : ''}>${name}</option>`
      )
      .join(
        ''
      )}</select></div>${field('语速调整（%）', 'rate', a.rate, 'number', '-50 到 +50；0 为正常语速', false, 'min="-50" max="50" required')}</div><div class="form-actions"><span class="form-note">保存后，下次设备新连接生效。</span><button class="button" type="submit">保存角色</button></div></form>`
  );
}
function deviceModal(device) {
  modal(
    device ? '编辑设备' : '添加一台设备',
    `<p class="explainer">为你的设备设置一个名字，并选择与它相伴的角色。</p><form id="device-form" data-mac="${esc(device?.mac || '')}"><div class="form-grid">${field('设备名称', 'name', device?.name || '小智桌面伙伴', 'text', '', true, 'required maxlength="80"')}${device ? '' : field('设备 MAC 地址', 'mac', '', 'text', '可从设备串口日志中查看', true, 'required placeholder="10:20:ba:00:00:01" pattern="([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}"')}<div class="field full"><label for="agent_id">使用角色</label><select id="agent_id" name="agent_id">${agentOptions(device?.agent_id)}</select></div></div><div class="form-actions"><span class="form-note">添加后还需要在板子上配置接入地址。</span><button class="button" type="submit">${device ? '保存设备' : '添加设备'}</button></div></form>`
  );
}
async function showConnection(mac) {
  const result = await api('/devices/' + encodeURIComponent(mac) + '/connection');
  modal(
    '设备接入地址',
    `<p class="explainer">在板子配网页面，将 OTA 服务地址设为下面的专属地址。这个地址包含接入凭据，请仅用于你自己的板子。</p><div class="connection-code" id="connection-url">${esc(result.ota_url)}</div>${result.local_only ? '<div class="notice">当前地址指向本机回环地址，板子无法直接访问。请先打通网络，并设置服务的 ESP_PUBLIC_URL 与 ESP_WS_URL。</div>' : '<div class="notice">确认板子能访问此地址，再切换服务。首次连接会绑定设备的 Client ID。</div>'}<div class="form-actions"><button class="button" data-action="copy-connection">${icon('copy')}复制地址</button></div>`
  );
}
document.addEventListener('click', async (event) => {
  const target = event.target.closest('button,a');
  if (!target) return;
  try {
    if (target.dataset.page) {
      event.preventDefault();
      await navigate(target.dataset.page);
      return;
    }
    if (target.dataset.editAgent) {
      agentModal(state.overview.agents.find((a) => a.id === target.dataset.editAgent));
      return;
    }
    if (target.dataset.editDevice) {
      deviceModal(state.overview.devices.find((d) => d.mac === target.dataset.editDevice));
      return;
    }
    if (target.dataset.connection) {
      await showConnection(target.dataset.connection);
      return;
    }
    const action = target.dataset.action;
    if (action === 'close-modal') $('#dialog').close();
    else if (action === 'retry') await boot();
    else if (action === 'logout') {
      await api('/logout', body('POST', {}));
      state.user = null;
      state.chat = [];
      state.session = null;
      $('#dialog').close();
      await boot();
    } else if (action === 'refresh') {
      target.disabled = true;
      await navigate(state.page);
      toast('状态已更新');
    } else if (action === 'add-agent') agentModal();
    else if (action === 'add-device') deviceModal();
    else if (action === 'open-chat') await navigate('chat');
    else if (action === 'copy-connection') {
      await navigator.clipboard.writeText($('#connection-url').textContent);
      toast('接入地址已复制');
    } else if (action === 'new-chat') {
      state.chat = [];
      state.session = null;
      renderPage();
    } else if (action === 'test-model') {
      if (state.modelDirty) {
        toast('请先保存配置，再测试连接');
        return;
      }
      target.disabled = true;
      target.textContent = '正在连接…';
      try {
        const result = await api('/model/test', body('POST', {}));
        if ($('#test-result')) {
          $('#test-result').textContent = `连接成功 · ${result.latency_ms} ms\n${result.reply}`;
          $('#test-result').classList.add('visible');
        }
      } finally {
        target.disabled = false;
        target.textContent = '测试连接';
      }
    }
  } catch (error) {
    toast(error.message);
    target.disabled = false;
  }
});
document.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const values = Object.fromEntries(new FormData(form));
  const submit = form.querySelector('[type=submit]');
  if (submit) submit.disabled = true;
  try {
    if (form.id === 'auth-form') {
      await api(form.dataset.setup === 'true' ? '/setup' : '/login', body('POST', values));
      state.page = 'home';
      await boot();
    } else if (form.id === 'model-form') {
      values.temperature = Number(values.temperature);
      values.max_tokens = Number(values.max_tokens);
      state.overview.model = await api('/model', body('PUT', values));
      state.modelDirty = false;
      toast('模型配置已保存');
      await navigate('model');
    } else if (form.id === 'agent-form') {
      values.rate = Number(values.rate);
      await api(
        '/agents' + (form.dataset.id ? '/' + form.dataset.id : ''),
        body(form.dataset.id ? 'PUT' : 'POST', values)
      );
      $('#dialog').close();
      await refresh();
      renderShell();
      toast('角色已保存，下次设备新连接时生效');
    } else if (form.id === 'device-form') {
      const mac = form.dataset.mac;
      await api(
        '/devices' + (mac ? '/' + encodeURIComponent(mac) : ''),
        body(mac ? 'PUT' : 'POST', values)
      );
      $('#dialog').close();
      await navigate('devices');
      toast(mac ? '设备已保存' : '设备已添加，等待接入');
    } else if (form.id === 'chat-form') {
      const content = values.text.trim();
      if (!content || state.sending) return;
      state.chat.push({ role: 'user', content });
      state.sending = true;
      const agentId = state.chatAgent;
      renderPage();
      try {
        const result = await api(
          '/chat',
          body('POST', {
            agent_id: agentId,
            text: content,
            session_id: state.session,
          })
        );
        state.session = result.session_id;
        state.chat.push({ role: 'assistant', content: result.reply });
      } catch (error) {
        state.chat.pop();
        throw error;
      } finally {
        state.sending = false;
        if (state.page === 'chat') {
          renderPage();
          $('#chat-input')?.focus();
        }
      }
    }
  } catch (error) {
    if (form.id === 'auth-form') $('#auth-error').textContent = error.message;
    else toast(error.message);
  } finally {
    if (submit) submit.disabled = false;
  }
});
document.addEventListener('input', (event) => {
  if (event.target.closest('#model-form')) state.modelDirty = true;
});
document.addEventListener('change', (event) => {
  if (event.target.id === 'provider') {
    const cloud = event.target.value === 'openai';
    $('#base_url').value = cloud ? '' : 'http://127.0.0.1:11434/v1';
    $('#base_url').placeholder = cloud ? 'https://你的服务地址/v1' : '';
    $('#api_key').value = '';
    state.modelDirty = true;
  } else if (event.target.id === 'chat-agent') {
    state.chatAgent = event.target.value;
    state.session = null;
    state.chat = [];
    renderPage();
  }
});
document.addEventListener('keydown', (event) => {
  if (
    event.target.id === 'chat-input' &&
    event.key === 'Enter' &&
    !event.shiftKey &&
    !event.isComposing
  ) {
    event.preventDefault();
    $('#chat-form').requestSubmit();
  }
});
$('#dialog').addEventListener('click', (event) => {
  if (event.target === $('#dialog')) {
    const rect = event.target.getBoundingClientRect();
    if (
      event.clientX < rect.left ||
      event.clientX > rect.right ||
      event.clientY < rect.top ||
      event.clientY > rect.bottom
    )
      event.target.close();
  }
});
state.page = pages[location.hash.slice(1)] ? location.hash.slice(1) : 'home';
boot();
