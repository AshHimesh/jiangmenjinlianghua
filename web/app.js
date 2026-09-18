// 江门金量化 · 前端逻辑（阶段 3：实时行情 + AI 对话，含思考流程展示）

// ===== 状态 =====
let groups = [];
let quotes = {};
let currentName = null;

let providers = [];
let cfg = {};

let streaming = false;
let streamReqId = null;
let streamEls = null;
let lastQuestion = null;

let skillData = { skills: [], active: [], stats: {} };

function getApi() {
  return (window.pywebview && window.pywebview.api) || null;
}

// ===== 启动 =====
function init() {
  if (!getApi()) {
    document.getElementById('quoteName').textContent = '未连接到后端';
    document.getElementById('quoteTime').textContent = '请通过 main.py 启动本程序';
    return;
  }
  bindEvents();
  loadSymbols();
  loadConfig();
  setInterval(refreshQuotes, 1000);
}

// ================= 行情 =================
async function loadSymbols() {
  try {
    groups = await getApi().get_symbols();
    renderSidebar();
    if (groups.length && groups[0].items.length) {
      selectSymbol(groups[0].items[0].name);
    }
  } catch (e) {
    console.error('加载品种列表失败', e);
  }
}

async function refreshQuotes() {
  try {
    quotes = await getApi().get_quotes();
  } catch (e) {
    return;
  }
  updateSidebarPrices();
  if (currentName) renderQuote(currentName);
}

function renderSidebar() {
  const sidebar = document.getElementById('sidebar');
  sidebar.innerHTML = '';

  groups.forEach((group) => {
    const title = document.createElement('div');
    title.className = 'group-title';
    title.textContent = group.name;
    sidebar.appendChild(title);

    group.items.forEach((item) => {
      const el = document.createElement('div');
      el.className = 'symbol-item';
      el.dataset.name = item.name;

      const nameSpan = document.createElement('span');
      nameSpan.className = 's-name';
      nameSpan.textContent = item.name;

      const priceSpan = document.createElement('span');
      priceSpan.className = 's-price';
      priceSpan.dataset.name = item.name;
      priceSpan.textContent = '--';

      el.appendChild(nameSpan);
      el.appendChild(priceSpan);
      el.addEventListener('click', () => selectSymbol(item.name));
      sidebar.appendChild(el);
    });
  });
}

function updateSidebarPrices() {
  document.querySelectorAll('.s-price').forEach((span) => {
    const q = quotes[span.dataset.name];
    if (q && q.price != null) {
      span.textContent = formatPrice(q.price);
      span.className = 's-price ' + changeClass(q.change);
    }
  });
}

function selectSymbol(name) {
  currentName = name;
  document.querySelectorAll('.symbol-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.name === name);
  });
  renderQuote(name);
  // 后台预热该品种的多周期K线，提问时就不用等
  const api = getApi();
  if (api && api.prepare) {
    api.prepare(name).catch(() => {});
  }
}

function renderQuote(name) {
  document.getElementById('quoteName').textContent = name;

  const item = findItem(name);
  const q = quotes[name];

  const priceEl = document.getElementById('quotePrice');
  const changeEl = document.getElementById('quoteChange');
  const unitEl = document.getElementById('quoteUnit');
  const timeEl = document.getElementById('quoteTime');

  if (item) unitEl.textContent = item.unit;

  if (!q || q.price == null) {
    priceEl.textContent = '--';
    priceEl.className = 'quote-price flat';
    changeEl.textContent = '--';
    changeEl.className = 'quote-change flat';
    timeEl.textContent = '数据加载中…';
    return;
  }

  priceEl.textContent = formatPrice(q.price);
  priceEl.className = 'quote-price ' + changeClass(q.change);

  const sign = Number(q.change) >= 0 ? '+' : '';
  changeEl.textContent = sign + Number(q.change).toFixed(2) + '%';
  changeEl.className = 'quote-change ' + changeClass(q.change);

  timeEl.textContent = q.stale
    ? '更新时间 ' + (q.updated || '--') + '（数据延迟）'
    : '更新时间 ' + (q.updated || '--');
}

function findItem(name) {
  for (const g of groups) {
    for (const it of g.items) {
      if (it.name === name) return it;
    }
  }
  return null;
}

// ================= AI 设置 =================
async function loadConfig() {
  const api = getApi();
  if (!api) return;
  try {
    const data = await api.get_config();
    providers = data.providers || [];
    cfg = data.config || {};
    fillProviderSelect();
  } catch (e) {
    console.error('加载配置失败', e);
  }
}

function fillProviderSelect() {
  const sel = document.getElementById('cfgProvider');
  sel.innerHTML = '';
  providers.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name;
    sel.appendChild(opt);
  });
  sel.value = cfg.provider || 'deepseek';
  applyProvider(sel.value, false);
}

function applyProvider(pid, overwrite) {
  const p = providers.find((x) => x.id === pid);
  if (!p) return;
  document.getElementById('providerHint').textContent = p.hint || '';
  if (overwrite) {
    document.getElementById('cfgBaseUrl').value = p.base_url || '';
    document.getElementById('cfgModel').value = (p.models && p.models[0]) || '';
  }
  const dl = document.getElementById('modelOptions');
  dl.innerHTML = '';
  (p.models || []).forEach((m) => {
    const o = document.createElement('option');
    o.value = m;
    dl.appendChild(o);
  });
}

function openSettings() {
  document.getElementById('cfgProvider').value = cfg.provider || 'deepseek';
  document.getElementById('cfgBaseUrl').value = cfg.base_url || '';
  document.getElementById('cfgApiKey').value = cfg.api_key || '';
  document.getElementById('cfgModel').value = cfg.model || '';
  document.getElementById('cfgInject').checked = cfg.inject_market !== false;
  document.getElementById('cfgTools').checked = cfg.enable_tools !== false;
  applyProvider(cfg.provider || 'deepseek', false);
  document.getElementById('saveHint').textContent = '';
  document.getElementById('skillHint').textContent = '勾选的技能会注入 AI，并作为必须遵守的分析规程。';
  document.getElementById('settingsMask').classList.add('show');
  loadSkills();
  loadCacheStats();
}

function closeSettings() {
  document.getElementById('settingsMask').classList.remove('show');
}

async function saveSettings() {
  const api = getApi();
  if (!api) return;
  const payload = {
    provider: document.getElementById('cfgProvider').value,
    base_url: document.getElementById('cfgBaseUrl').value.trim(),
    api_key: document.getElementById('cfgApiKey').value.trim(),
    model: document.getElementById('cfgModel').value.trim(),
    inject_market: document.getElementById('cfgInject').checked,
    enable_tools: document.getElementById('cfgTools').checked,
  };
  try {
    cfg = await api.save_config(payload);
    document.getElementById('saveHint').textContent = '已保存 ✓';
    setTimeout(closeSettings, 600);
  } catch (e) {
    document.getElementById('saveHint').textContent = '保存失败：' + e;
  }
}

// ================= 技能 Skill =================
async function loadSkills() {
  const api = getApi();
  if (!api) return;
  try {
    skillData = await api.get_skills();
    renderSkills();
  } catch (e) {
    console.error('读取技能失败', e);
  }
}

function renderSkills() {
  const box = document.getElementById('skillList');
  const list = skillData.skills || [];
  box.innerHTML = '';

  if (!list.length) {
    const empty = document.createElement('div');
    empty.className = 'skill-empty';
    empty.textContent = '暂无技能文件。把 .txt 或 .md 文件放进项目的 skills 文件夹，或点下方按钮导入。';
    box.appendChild(empty);
  } else {
    list.forEach((s) => {
      const row = document.createElement('label');
      row.className = 'skill-item';

      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !!s.active;
      cb.addEventListener('change', () => onSkillToggle(s.filename, cb.checked));

      const nm = document.createElement('span');
      nm.className = 'skill-name';
      nm.textContent = s.name;
      nm.title = s.filename;

      const sz = document.createElement('span');
      sz.className = 'skill-size';
      sz.textContent = '约 ' + Math.round(s.chars / 2) + ' tokens';

      row.appendChild(cb);
      row.appendChild(nm);
      row.appendChild(sz);
      box.appendChild(row);
    });
  }

  const st = skillData.stats || {};
  document.getElementById('skillStats').textContent =
    st.count ? '已启用 ' + st.count + ' 个 · 约 ' + Math.round((st.chars || 0) / 2) + ' tokens' : '未启用';
}

async function onSkillToggle(filename, checked) {
  const api = getApi();
  if (!api) return;
  const current = (skillData.skills || []).filter((s) => s.active).map((s) => s.filename);
  let next;
  if (checked) {
    next = current.concat([filename]);
  } else {
    next = current.filter((f) => f !== filename);
  }
  try {
    skillData = await api.set_skills(next);
    renderSkills();
  } catch (e) {
    console.error('保存技能设置失败', e);
  }
}

async function importSkill() {
  const api = getApi();
  if (!api) return;
  const hint = document.getElementById('skillHint');
  try {
    const res = await api.import_skill_dialog();
    if (res && res.cancelled) return;
    if (res && res.error) {
      hint.textContent = res.error;
      return;
    }
    if (res && res.data) {
      skillData = res.data;
      renderSkills();
      hint.textContent = '已导入：' + res.filename;
    }
  } catch (e) {
    hint.textContent = '导入失败：' + e;
  }
}

// ================= 缓存 =================
async function loadCacheStats() {
  const api = getApi();
  if (!api) return;
  try {
    const s = await api.get_cache_stats();
    document.getElementById('cacheStats').textContent =
      '共 ' + s.total + ' 条，其中有效 ' + s.fresh + ' 条（有效期 ' + s.ttl_minutes + ' 分钟）';
  } catch (e) {
    /* ignore */
  }
}

async function clearCache() {
  const api = getApi();
  if (!api) return;
  try {
    await api.clear_cache();
    await loadCacheStats();
  } catch (e) {
    /* ignore */
  }
}

// ================= 对话 =================
async function sendMessage() {
  if (streaming) return;
  const api = getApi();
  if (!api) return;

  const input = document.getElementById('chatInput');
  const text = input.value.trim();
  if (!text) return;

  input.value = '';
  autoGrow(input);
  addUserMsg(text);
  lastQuestion = text;
  startStream(text, false);
}

// 忽略缓存，重新向 AI 提问
async function regenerate() {
  if (streaming || !lastQuestion) return;
  startStream(lastQuestion, true);
}

async function startStream(question, force) {
  const api = getApi();
  if (!api) return;

  const els = addAiMsg();
  streaming = true;
  streamEls = els;
  updateSendState();

  let res;
  try {
    res = await api.ask(question, currentName, !!force);
  } catch (e) {
    showAiError(els, '调用失败：' + e);
    finishStream();
    return;
  }

  if (!res || res.error) {
    showAiError(els, (res && res.error) || '调用失败');
    finishStream();
    return;
  }

  streamReqId = res.id;
  pollStream();
}

async function pollStream() {
  const api = getApi();
  const els = streamEls;
  if (!api || !els || !streamReqId) {
    finishStream();
    return;
  }

  let st;
  try {
    st = await api.get_stream(streamReqId);
  } catch (e) {
    showAiError(els, '读取回答失败：' + e);
    finishStream();
    return;
  }

  if (!st) {
    finishStream();
    return;
  }

  updateAiMsg(els, st);

  if (st.done) {
    if (st.error) {
      showAiError(els, st.error);
    } else if (!st.content) {
      showAiError(els, '模型没有返回内容，请检查模型名称是否正确。');
    }
    finishStream();
    return;
  }

  setTimeout(pollStream, 120);
}

function finishStream() {
  streaming = false;
  streamReqId = null;
  streamEls = null;
  updateSendState();
}

function updateSendState() {
  document.getElementById('chatSend').disabled = streaming;
}

function addUserMsg(text) {
  const box = document.getElementById('chatMessages');
  const el = document.createElement('div');
  el.className = 'msg user';
  el.textContent = text;
  box.appendChild(el);
  scrollChat();
}

function addAiMsg() {
  const box = document.getElementById('chatMessages');

  const el = document.createElement('div');
  el.className = 'msg ai';

  const thinking = document.createElement('div');
  thinking.className = 'thinking collapsed';
  thinking.style.display = 'none';

  const head = document.createElement('div');
  head.className = 'thinking-head';
  const dot = document.createElement('span');
  dot.className = 'thinking-dot';
  const title = document.createElement('span');
  title.className = 'thinking-title';
  title.textContent = '思考中…';
  const arrow = document.createElement('span');
  arrow.className = 'thinking-arrow';
  arrow.textContent = '▾';
  head.appendChild(dot);
  head.appendChild(title);
  head.appendChild(arrow);

  const body = document.createElement('div');
  body.className = 'thinking-body';

  thinking.appendChild(head);
  thinking.appendChild(body);

  const placeholder = document.createElement('div');
  placeholder.className = 'chat-placeholder';
  placeholder.textContent = '正在思考…';

  const answer = document.createElement('div');
  answer.className = 'answer-text';
  answer.style.display = 'none';

  const cacheNote = document.createElement('div');
  cacheNote.className = 'cache-note';
  cacheNote.style.display = 'none';

  const toolList = document.createElement('div');
  toolList.className = 'tool-list';
  toolList.style.display = 'none';

  el.appendChild(cacheNote);
  el.appendChild(toolList);
  el.appendChild(thinking);
  el.appendChild(placeholder);
  el.appendChild(answer);
  box.appendChild(el);

  const els = {
    el: el,
    thinking: thinking,
    head: head,
    title: title,
    body: body,
    placeholder: placeholder,
    answer: answer,
    cacheNote: cacheNote,
    toolList: toolList,
    toolSig: '',
    cacheShown: false,
    userToggled: false,
  };

  head.addEventListener('click', () => {
    thinking.classList.toggle('collapsed');
    els.userToggled = true;
  });

  scrollChat();
  return els;
}

function updateAiMsg(els, st) {
  // 缓存命中提示
  if (st.cached && !els.cacheShown) {
    els.cacheShown = true;
    els.cacheNote.style.display = '';
    const txt = document.createElement('span');
    const mins = st.cache_age != null ? Math.max(1, Math.round(st.cache_age / 60)) : 0;
    const sim = st.cache_similarity != null ? Math.round(st.cache_similarity * 100) : 100;
    txt.textContent = (sim >= 100 ? '⚡ 命中缓存' : '⚡ 相似问题命中缓存（相似度 ' + sim + '%）')
                    + (mins ? ' · ' + mins + ' 分钟前的回答' : '');
    const btn = document.createElement('button');
    btn.className = 'cache-regen';
    btn.textContent = '重新生成';
    btn.addEventListener('click', regenerate);
    els.cacheNote.appendChild(txt);
    els.cacheNote.appendChild(btn);
  }

  // AI 工具调用记录
  renderToolList(els, st.tools);

  // 思考过程
  if (st.thinking) {
    els.thinking.style.display = '';
    els.body.textContent = st.thinking;

    if (st.thinking_done) {
      els.head.classList.remove('pulsing');
      els.title.textContent = '已深度思考（用时 ' + st.thinking_seconds + ' 秒）';
      if (!els.userToggled) {
        els.thinking.classList.add('collapsed');
      }
    } else {
      els.head.classList.add('pulsing');
      els.title.textContent = '思考中…';
      if (!els.userToggled) {
        els.thinking.classList.remove('collapsed');
      }
    }
  }

  // 正文
  if (st.content) {
    els.answer.textContent = st.content;
    els.answer.style.display = '';
    els.placeholder.style.display = 'none';
  } else if (!st.done) {
    els.placeholder.textContent = st.thinking ? '正在组织回答…' : '正在思考…';
  }

  if (st.done) {
    els.head.classList.remove('pulsing');
    if (!st.content) {
      els.placeholder.style.display = 'none';
    }
  }

  scrollChat();
}

function renderToolList(els, tools) {
  const list = tools || [];
  const sig = list.map((t) => t.label + ':' + t.status).join('|');
  if (sig === els.toolSig) return;
  els.toolSig = sig;

  els.toolList.innerHTML = '';
  if (!list.length) {
    els.toolList.style.display = 'none';
    return;
  }
  els.toolList.style.display = '';

  list.forEach((t) => {
    const row = document.createElement('div');
    row.className = 'tool-item ' + (t.status === 'running' ? 'running' : 'done');

    const icon = document.createElement('span');
    icon.className = 'tool-icon';
    icon.textContent = t.status === 'running' ? '◌' : '✓';

    const txt = document.createElement('span');
    txt.textContent = t.label;

    row.appendChild(icon);
    row.appendChild(txt);
    els.toolList.appendChild(row);
  });
  scrollChat();
}

function showAiError(els, msg) {
  els.placeholder.style.display = 'none';
  els.head.classList.remove('pulsing');
  els.el.className = 'msg error';
  els.answer.style.display = '';
  els.answer.textContent = msg;
  scrollChat();
}

async function clearChat() {
  const api = getApi();
  if (!api) return;
  try {
    await api.clear_chat();
  } catch (e) {
    /* ignore */
  }
  const box = document.getElementById('chatMessages');
  box.innerHTML = '<div class="msg ai">对话已清空。选中左侧品种后可以继续提问。</div>';
}

// ================= 事件绑定 =================
function bindEvents() {
  document.getElementById('gearBtn').addEventListener('click', openSettings);
  document.getElementById('settingsClose').addEventListener('click', closeSettings);
  document.getElementById('cfgSave').addEventListener('click', saveSettings);
  document.getElementById('cfgProvider').addEventListener('change', (e) => {
    applyProvider(e.target.value, true);
  });
  document.getElementById('settingsMask').addEventListener('click', (e) => {
    if (e.target.id === 'settingsMask') closeSettings();
  });
  document.getElementById('importSkillBtn').addEventListener('click', importSkill);
  document.getElementById('clearCacheBtn').addEventListener('click', clearCache);

  const input = document.getElementById('chatInput');
  input.addEventListener('input', () => autoGrow(input));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  document.getElementById('chatSend').addEventListener('click', sendMessage);
  document.getElementById('clearBtn').addEventListener('click', clearChat);
}

// ================= 工具 =================
function autoGrow(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function scrollChat() {
  const box = document.getElementById('chatMessages');
  box.scrollTop = box.scrollHeight;
}

function changeClass(change) {
  const c = Number(change);
  if (c > 0) return 'up';
  if (c < 0) return 'down';
  return 'flat';
}

function formatPrice(p) {
  return Number(p).toLocaleString('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

// ================= 启动 =================
if (getApi()) {
  init();
} else {
  window.addEventListener('pywebviewready', init);
}
