/* 淘宝商品素材采集与创作工具 · 前端逻辑 */
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const state = {
  tasks: [],
  currentId: null,
  meta: null,
  stats: null,
  raw: {},
  outputs: {},
  templates: null,
  settings: null,
  activeTab: 'overview',
  pollTimer: null,
  suggestions: null,
  slotOptions: null,
  global: { accent: '#E8467C', bg: '#F7F4F0', text_color: '#1A1A1A' },
  detailSelection: new Set(),
  detailBusy: new Set(),
  detailAutoOrder: true,
  keywordDraft: null,
  analysis: null,
  selectedWords: new Set(),
  rawKind: 'main',
  exportSections: null,
  autoOpenFolder: true,
  previewKey: null,
  previewData: null,
  previewTimer: null,
  slotPreviewVariants: {},
  slotRequests: new Map(),
  selectedPreset: 'rose',
  colorPresets: [
    { id: 'rose', name: '经典玫红', accent: '#E8467C', bg: '#F7F4F0', text: '#1A1A1A' },
    { id: 'blue', name: '通勤蓝', accent: '#2F80ED', bg: '#F5F8FC', text: '#1A1A1A' },
    { id: 'green', name: '森系绿', accent: '#2E7D5B', bg: '#F4F8F4', text: '#1A1A1A' },
    { id: 'black', name: '高级黑', accent: '#1F2430', bg: '#F5F5F5', text: '#1A1A1A' },
    { id: 'orange', name: '暖橙', accent: '#E07A3F', bg: '#FFF8F2', text: '#1A1A1A' },
    { id: 'coffee', name: '奶咖', accent: '#8D6E63', bg: '#F8F4EF', text: '#1A1A1A' },
  ],
};

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function fmtBytes(bytes) {
  const value = Number(bytes || 0);
  if (value < 1024) return value + ' B';
  if (value < 1024 * 1024) return (value / 1024).toFixed(1) + ' KB';
  return (value / 1024 / 1024).toFixed(2) + ' MB';
}

function fmtDate(value) {
  if (!value) return '—';
  return String(value).replace('T', ' ').slice(0, 19);
}

function statusInfo(status) {
  const map = {
    created: ['已创建', ''],
    collecting: ['采集中', 'warn'],
    collected: ['已归档', 'success'],
    collected_partial: ['部分归档', 'warn'],
    generating: ['出图中', 'warn'],
    generated: ['已出图', 'success'],
    exported: ['已导出', 'success'],
    failed: ['失败', 'danger'],
  };
  const info = map[status] || [status || '未知', ''];
  return { text: info[0], cls: info[1] };
}

async function api(path, options = {}) {
  const opts = { ...options };
  if (opts.json !== undefined) {
    opts.headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
    opts.body = JSON.stringify(opts.json);
  }
  let response;
  try {
    response = await fetch(path, opts);
  } catch (error) {
    throw new Error('无法连接到本地服务：' + error.message);
  }
  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error('服务响应格式错误');
  }
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `请求失败 (${response.status})`);
  }
  return data.data;
}

function toast(message, type = '') {
  const element = document.createElement('div');
  element.className = 'toast ' + type;
  element.textContent = message;
  $('#toastRoot').appendChild(element);
  setTimeout(() => element.remove(), 4000);
}

function openModal({ title, body, foot = '', className = '', onMount = null, lightbox = false }) {
  $('#modalRoot').innerHTML = `
    <div class="modal-backdrop">
      <div class="modal ${className} ${lightbox ? 'lightbox' : ''}">
        <div class="modal-head">
          <h3>${esc(title)}</h3>
          <button class="modal-close" title="关闭">×</button>
        </div>
        <div class="modal-body">${body}</div>
        ${foot ? `<div class="modal-foot">${foot}</div>` : ''}
      </div>
    </div>`;
  $('.modal-close').onclick = closeModal;
  const backdrop = $('.modal-backdrop');
  backdrop.addEventListener('click', (event) => {
    if (event.target === backdrop) closeModal();
  });
  if (onMount) onMount($('#modalRoot'));
}

function closeModal() {
  $('#modalRoot').innerHTML = '';
}

function mediaUrl(taskId, rel, width = 0) {
  const parts = String(rel).split('/').map(encodeURIComponent).join('/');
  return `/media/${encodeURIComponent(taskId)}/${parts}${width ? '?w=' + width : ''}`;
}

function currentMedia(rel, width = 0) {
  const url = mediaUrl(state.currentId, rel, width);
  if (!String(rel).startsWith('output/')) return url;
  const outputs = state.meta?.outputs;
  const record = [...asRecordList(outputs?.main_pc), ...asRecordList(outputs?.main_mobile)]
    .find((item) => item?.file === rel);
  const revision = record?.editedAt || record?.previewVersion || record?.updatedAt;
  return revision ? `${url}${width ? '&' : '?'}v=${encodeURIComponent(revision)}` : url;
}

function asRecordList(value) {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') return Object.values(value);
  return [];
}

function taskUrl(path) {
  return `/api/tasks/${encodeURIComponent(state.currentId)}${path}`;
}

function schedulePoll() {
  clearTimeout(state.pollTimer);
  state.pollTimer = setTimeout(async () => {
    if (!state.currentId) return;
    try {
      await refreshTask();
    } catch (error) {
      toast(error.message, 'error');
    }
  }, 1500);
}

async function loadTasks() {
  state.tasks = await api('/api/tasks');
  renderTaskList();
}

function renderTaskList() {
  $('#taskCount').textContent = String(state.tasks.length);
  const list = $('#taskList');
  if (!state.tasks.length) {
    list.innerHTML = '<div class="small muted" style="padding:8px 4px">暂无任务</div>';
    return;
  }
  list.innerHTML = state.tasks.map((task) => {
    const cover = task.cover
      ? `<img class="task-cover" src="${mediaUrl(task.id, task.cover, 88)}" alt="">`
      : '<div class="task-cover" style="display:flex;align-items:center;justify-content:center;color:#bbb">图</div>';
    const status = statusInfo(task.status);
    const counts = task.stats && task.stats.rawCounts ? task.stats.rawCounts : {};
    return `
      <button class="task-item ${task.id === state.currentId ? 'active' : ''}" data-id="${esc(task.id)}">
        ${cover}
        <div class="task-info">
          <div class="task-title">${esc(task.title)}</div>
          <div class="task-sub">
            <span class="status-dot ${status.cls}"></span>${esc(status.text)} ·
            ${counts.main || 0} 主图 / ${counts.detail || 0} 详情${counts.review ? ` / ${counts.review} 待确认` : ''}
          </div>
        </div>
      </button>`;
  }).join('');
  $$('.task-item', list).forEach((button) => {
    button.onclick = () => selectTask(button.dataset.id);
  });
}

async function selectTask(id) {
  state.currentId = id;
  state.slotPreviewVariants = {};
  state.suggestions = null;
  state.slotOptions = null;
  state.keywordDraft = null;
  state.analysis = null;
  state.selectedWords = new Set();
  state.detailSelection = new Set();
  state.detailAutoOrder = true;
  state.exportSections = null;
  $('#emptyState').classList.add('hidden');
  $('#taskView').classList.remove('hidden');
  await refreshTask();
  switchTab('overview');
}

async function refreshTask() {
  if (!state.currentId) return;
  const data = await api(taskUrl(''));
  state.meta = data.meta;
  state.stats = data.stats;
  state.raw = data.raw;
  state.outputs = data.outputs;
  const taskSummary = state.tasks.find((task) => task.id === state.currentId);
  if (taskSummary) {
    taskSummary.title = state.meta.title;
    taskSummary.status = state.meta.status;
    taskSummary.statusText = state.meta.statusText;
    taskSummary.lastError = state.meta.lastError;
    taskSummary.stats = state.stats;
    taskSummary.cover = ['main', 'detail', 'sku', 'review']
      .map((kind) => (state.meta.raw[kind] || [])[0]?.file)
      .find(Boolean) || '';
  }
  renderTaskHeader();
  renderTaskList();
  await renderActivePanel();
  if (['collecting', 'generating'].includes(state.meta.status)) {
    schedulePoll();
  } else {
    clearTimeout(state.pollTimer);
  }
}

function renderTaskHeader() {
  const meta = state.meta;
  const status = statusInfo(meta.status);
  const progress = meta.progress || {};
  const pct = progress.total ? Math.round((progress.done || 0) / progress.total * 100) : 0;
  const counts = (state.stats && state.stats.rawCounts) || {};
  const out = (state.stats && state.stats.outputCounts) || {};
  $('#taskHeader').innerHTML = `
    <div class="header-top">
      <div>
        <h1 class="header-title">${esc(meta.title)}</h1>
        <div class="header-meta">
          <span class="badge ${status.cls}"><span class="status-dot ${status.cls}"></span>${esc(status.text)}</span>
          <span>商品ID：${esc(meta.offerId || '—')}</span>
          <span>${meta.sourceUrl ? `<a href="${esc(meta.sourceUrl)}" target="_blank" rel="noopener">来源链接</a>` : '无来源链接'}</span>
          <span>创建：${esc(fmtDate(meta.createdAt))}</span>
        </div>
        ${meta.status === 'collecting' ? `
          <div class="progress"><div style="width:${pct}%"></div></div>
          <div class="small muted mt-8">采集中 ${progress.done || 0} / ${progress.total || 0}</div>` : ''}
        ${meta.lastError ? `<div class="alert alert-error mt-12">${esc(meta.lastError)}</div>` : ''}
        <div class="stat-pills">
          <div class="stat-pill">主图原图<strong>${counts.main || 0}</strong></div>
          <div class="stat-pill">详情原图<strong>${counts.detail || 0}</strong></div>
          <div class="stat-pill">SKU<strong>${counts.sku || 0}</strong></div>
          ${counts.review ? `<div class="stat-pill">待确认<strong>${counts.review}</strong></div>` : ''}
          <div class="stat-pill">PC主图<strong>${out.main_pc || 0}</strong></div>
          <div class="stat-pill">手机主图<strong>${out.main_mobile || 0}</strong></div>
          <div class="stat-pill">详情成品<strong>${out.detail || 0}</strong></div>
          <div class="stat-pill">SKU成品<strong>${out.sku || 0}</strong></div>
          <div class="stat-pill">编辑成品<strong>${out.edited || 0}</strong></div>
        </div>
      </div>
      <div class="header-actions">
        <button class="btn btn-sm" id="btnOpenFolder">打开文件夹</button>
        <button class="btn btn-sm" id="btnRecollect">重新采集</button>
        <button class="btn btn-sm btn-danger" id="btnDelete">删除任务</button>
      </div>
    </div>`;
  $('#btnOpenFolder').onclick = async () => {
    try {
      await api(taskUrl('/open-folder'), { method: 'POST' });
    } catch (error) {
      toast(error.message, 'error');
    }
  };
  $('#btnRecollect').onclick = async () => {
    try {
      await api(taskUrl('/collect'), { method: 'POST', json: {} });
      toast('已开始重新采集', 'success');
      await refreshTask();
    } catch (error) {
      toast(error.message, 'error');
    }
  };
  $('#btnDelete').onclick = async () => {
    if (!confirm('确定删除这个任务及全部素材吗？此操作不可恢复。')) return;
    try {
      await api(taskUrl(''), { method: 'DELETE' });
      state.currentId = null;
      clearTimeout(state.pollTimer);
      $('#taskView').classList.add('hidden');
      $('#emptyState').classList.remove('hidden');
      await loadTasks();
      toast('任务已删除', 'success');
    } catch (error) {
      toast(error.message, 'error');
    }
  };
}

function switchTab(tab) {
  state.activeTab = tab;
  $$('.tabs button').forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === tab);
  });
  $$('.tab-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id === 'panel-' + tab);
  });
  return renderActivePanel();
}

async function renderActivePanel() {
  try {
    if (state.activeTab === 'overview') renderOverview();
    else if (state.activeTab === 'raw') renderRaw();
    else if (state.activeTab === 'create') await renderCreate();
    else if (state.activeTab === 'keywords') await renderKeywords();
    else if (state.activeTab === 'export') renderExport();
  } catch (error) {
    toast(error.message, 'error');
    const panel = $('#panel-' + state.activeTab);
    if (panel) panel.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

function renderOverview() {
  const meta = state.meta;
  const skuRows = (meta.sku || []).map((item, index) => `
    <tr>
      <td>${index + 1}</td>
      <td>${esc(item.name || '—')}</td>
      <td>${esc(item.price || '—')}</td>
      <td>${esc(item.stock || '—')}</td>
      <td>${item.image ? `<a href="javascript:void(0)" class="preview-link" data-rel="${esc(item.image)}">查看</a>` : '—'}</td>
    </tr>`).join('');
  const logs = (meta.logs || []).slice(-25).reverse().map((log) => `
    <div class="small" style="padding:4px 0;border-bottom:1px solid var(--line-soft)">
      <span class="muted">${esc(fmtDate(log.time))}</span>
      <span class="${log.level === 'error' ? 'muted' : ''}" style="margin-left:10px;color:${log.level === 'error' ? 'var(--danger)' : 'inherit'}">${esc(log.message)}</span>
    </div>`).join('');
  $('#panel-overview').innerHTML = `
    <div class="grid grid-2">
      <div class="card">
        <div class="card-head"><h3>商品信息</h3></div>
        <div class="card-body">
          <dl class="info-list">
            <dt>标题</dt><dd>${esc(meta.title)}</dd>
            <dt>商品 ID</dt><dd>${esc(meta.offerId || '—')}</dd>
            <dt>价格</dt><dd>${esc(meta.price || '—')}</dd>
            <dt>类目</dt><dd>${esc(meta.category || '—')}</dd>
            <dt>来源</dt><dd>${meta.sourceUrl ? esc(meta.sourceUrl) : '—'}</dd>
            <dt>状态</dt><dd>${esc(statusInfo(meta.status).text)}</dd>
          </dl>
          <div class="row mt-16">
            <button class="btn btn-secondary btn-sm" data-goto="raw">查看素材</button>
            <button class="btn btn-secondary btn-sm" data-goto="create">开始出图</button>
            <button class="btn btn-secondary btn-sm" data-goto="keywords">配置关键词</button>
          </div>
        </div>
      </div>
      <div class="card">
        <div class="card-head"><h3>SKU 规格</h3><span class="sub">${(meta.sku || []).length} 项</span></div>
        <div class="card-body" style="padding:0;overflow-x:auto">
          ${skuRows ? `<table><thead><tr><th>#</th><th>规格名</th><th>价格</th><th>库存</th><th>图片</th></tr></thead><tbody>${skuRows}</tbody></table>` : '<div class="card-body muted small">暂无 SKU 信息</div>'}
        </div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>AI 商品分析</h3><span class="sub">本地规则可用，模型接入后可增强</span></div>
      <div class="card-body">
        <div class="small muted">${meta.aiAnalysis ? `关键词：${esc((meta.aiAnalysis.keywords || []).join('、'))}` : '尚未分析商品'}</div>
        <div class="row mt-16"><button class="btn btn-secondary btn-sm" id="runAiAnalysis">分析商品</button><button class="btn btn-secondary btn-sm" id="openAiAssistant">自然语言修改设计</button><button class="btn btn-ghost btn-sm" id="aiUndo">撤销</button><button class="btn btn-ghost btn-sm" id="aiRedo">重做</button></div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>操作日志</h3></div>
      <div class="card-body">${logs || '<div class="small muted">暂无日志</div>'}</div>
    </div>`;
  $$('[data-goto]', $('#panel-overview')).forEach((button) => {
    button.onclick = () => switchTab(button.dataset.goto);
  });
  $$('.preview-link', $('#panel-overview')).forEach((link) => {
    link.onclick = () => openLightbox(link.dataset.rel);
  });
  $('#runAiAnalysis').onclick = async () => {
    try { await api(taskUrl('/ai/analyze'), { method: 'POST', json: {} }); await refreshTask(); toast('商品分析已完成', 'success'); }
    catch (error) { toast(error.message, 'error'); }
  };
  $('#openAiAssistant').onclick = openAiAssistant;
  $('#aiUndo').onclick = () => applyAiHistoryAction('undo');
  $('#aiRedo').onclick = () => applyAiHistoryAction('redo');
}

async function applyAiHistoryAction(action) {
  try {
    await api(taskUrl(`/ai/assistant/${action}`), { method: 'POST', json: {} });
    await refreshTask();
    toast(action === 'undo' ? '已撤销设计修改' : '已重做设计修改', 'success');
  } catch (error) { toast(error.message, 'error'); }
}

function openAiAssistant() {
  openModal({
    title: 'AI 设计助手',
    body: '<label class="field"><span>告诉我你想怎么修改</span><textarea id="aiInstruction" rows="4" placeholder="例如：把背景换成浅灰色，商品主体放大 20%，字体统一"></textarea></label><div id="aiPlan" class="mt-16"></div>',
    foot: '<button class="btn" id="aiPreviewBtn">预览修改</button><button class="btn btn-primary" id="aiApplyBtn" disabled>确认应用</button>',
    onMount: (root) => {
      let plan = null;
      $('#aiPreviewBtn', root).onclick = async () => {
        try {
          plan = await api(taskUrl('/ai/assistant/preview'), { method: 'POST', json: { instruction: $('#aiInstruction', root).value } });
          $('#aiPlan', root).innerHTML = `<div class="alert alert-info">将执行：${esc((plan.operations || []).map((item) => item.type).join('、') || '没有识别到可执行修改')}</div>`;
          $('#aiApplyBtn', root).disabled = !(plan.operations || []).length;
        } catch (error) { toast(error.message, 'error'); }
      };
      $('#aiApplyBtn', root).onclick = async () => {
        try { await api(taskUrl('/ai/assistant/apply'), { method: 'POST', json: { plan } }); closeModal(); await refreshTask(); toast('设计修改已应用', 'success'); }
        catch (error) { toast(error.message, 'error'); }
      };
    },
  });
}

function openLightbox(rel) {
  openModal({
    title: '素材预览',
    body: `<div style="text-align:center;background:#111;border-radius:8px;padding:12px"><img class="lightbox-img" src="${currentMedia(rel)}" alt=""></div>`,
    lightbox: true,
  });
}

const SOURCE_KIND_LABELS = { main: '主图', detail: '详情', sku: 'SKU', review: '待确认' };

function openSourcePicker(options = {}) {
  const title = options.title || '选择图片';
  const current = options.current || '';
  const kinds = options.kinds || ['main', 'detail', 'sku', 'review'];
  const allowUpload = options.allowUpload !== false;
  const onSelect = options.onSelect || null;
  const taskId = state.currentId;
  let selected = '';
  let activeKind = kinds.find((kind) => (state.raw[kind] || []).includes(current))
    || kinds.find((kind) => (state.raw[kind] || []).length) || kinds[0];
  const filename = (rel) => rel.split('/').pop();
  const preview = (rel, empty) => rel
    ? `<img src="${mediaUrl(taskId, rel, 760)}" alt="${esc(filename(rel))}">`
    : `<span>${empty}</span>`;
  const body = `
    <div class="replacement-layout">
      <section class="replacement-library" aria-label="素材库">
        <div class="replacement-filters" aria-label="素材分类"></div>
        <div class="replacement-grid"></div>
      </section>
      <section class="replacement-comparison" aria-label="素材对比">
        <figure><figcaption>当前素材</figcaption><div class="replacement-frame">${preview(current, '尚未选用素材')}</div>
          <div class="replacement-name" title="${esc(filename(current))}">${esc(filename(current))}</div></figure>
        <figure><figcaption>候选素材</figcaption><div class="replacement-frame" id="replacementPreview">${preview('', '从素材库选择一张图片')}</div>
          <div class="replacement-name" id="replacementName" aria-live="polite"></div></figure>
      </section>
    </div>
    ${allowUpload ? `
      <div class="picker-upload">
        <div class="row mt-8">
          <select id="pickerUploadKind" aria-label="上传素材分类">
            ${kinds.map((kind) => `<option value="${kind}">${SOURCE_KIND_LABELS[kind] || kind}</option>`).join('')}
          </select>
          <input type="file" id="pickerUploadFiles" accept="image/*" aria-label="选择本地图片">
          <button type="button" class="btn btn-secondary btn-sm" id="pickerUploadBtn">上传并预览</button>
        </div>
      </div>` : ''}`;
  openModal({
    title,
    className: 'wide replacement-modal',
    body,
    foot: '<button type="button" class="btn" id="replacementCancel">取消</button><button type="button" class="btn btn-primary" id="replacementApply" disabled>更换并更新两端</button>',
    onMount: (root) => {
      const grid = $('.replacement-grid', root);
      const filters = $('.replacement-filters', root);
      const dialog = $('.replacement-modal', root);
      const apply = $('#replacementApply', root);
      const cancel = $('#replacementCancel', root);
      let busy = false;
      const isOpen = () => dialog.isConnected && state.currentId === taskId;
      const select = (rel) => {
        selected = rel;
        $('#replacementPreview', dialog).innerHTML = preview(rel, '从素材库选择一张图片');
        const name = $('#replacementName', dialog);
        name.textContent = filename(rel);
        name.title = name.textContent;
        apply.disabled = busy || !rel || rel === current;
        $$('[data-pick-source]', grid).forEach((button) => {
          button.setAttribute('aria-pressed', String(button.dataset.pickSource === rel));
        });
      };
      const renderLibrary = () => {
        filters.innerHTML = kinds.map((kind) => `<button type="button" class="btn btn-sm" data-picker-kind="${esc(kind)}" aria-pressed="${kind === activeKind}">${esc(SOURCE_KIND_LABELS[kind] || kind)} <span>${(state.raw[kind] || []).length}</span></button>`).join('');
        grid.innerHTML = (state.raw[activeKind] || []).map((rel) => `
          <button type="button" class="replacement-thumb" data-pick-source="${esc(rel)}" aria-pressed="${rel === selected}" title="${esc(filename(rel))}">
            <span class="replacement-thumb-image"><img src="${mediaUrl(taskId, rel, 240)}" alt="" loading="lazy">${rel === current ? '<span class="replacement-current">当前</span>' : ''}</span>
            <span class="replacement-name">${esc(filename(rel))}</span>
          </button>`).join('') || '<p class="small muted">此分类暂无图片</p>';
        grid.scrollTop = 0;
      };
      filters.onclick = (event) => {
        const button = event.target.closest('[data-picker-kind]');
        if (!button || busy || button.dataset.pickerKind === activeKind) return;
        activeKind = button.dataset.pickerKind;
        renderLibrary();
        $('[aria-pressed="true"]', filters)?.focus();
      };
      grid.onclick = (event) => {
        const button = event.target.closest('[data-pick-source]');
        if (button && !busy) select(button.dataset.pickSource);
      };
      cancel.onclick = closeModal;
      apply.onclick = async () => {
        if (busy || !selected || selected === current) return;
        busy = true;
        apply.disabled = true;
        apply.textContent = '正在生成…';
        try {
          await onSelect?.(selected);
          if (isOpen()) closeModal();
        } catch (error) {
          toast(error.message, 'error');
        } finally {
          busy = false;
          apply.disabled = false;
          apply.textContent = '更换并更新两端';
        }
      };
      renderLibrary();
      if (!allowUpload) return;
      $('#pickerUploadBtn', root).onclick = async () => {
        if (busy) return;
        const input = $('#pickerUploadFiles', root);
        if (!input.files || !input.files.length) {
          toast('请先选择本地图片', 'error');
          return;
        }
        const button = $('#pickerUploadBtn', root);
        busy = true;
        apply.disabled = true;
        button.disabled = true;
        button.innerHTML = '<span class="spinner"></span> 上传中';
        try {
          const kind = $('#pickerUploadKind', root).value;
          const files = await uploadTaskFiles(input.files, kind);
          if (state.currentId !== taskId) return;
          await refreshTask();
          if (isOpen() && files.length) {
            activeKind = kind;
            selected = files[0];
            renderLibrary();
            input.value = '';
          }
        } catch (error) {
          toast(error.message, 'error');
        } finally {
          busy = false;
          button.disabled = false;
          button.textContent = '上传并预览';
          if (isOpen()) select(selected);
        }
      };
    },
  });
}

function disposeImageEditor() {
  if (state.editor && state.editor.canvas) {
    if (state.editor.keyHandler) {
      document.removeEventListener('keydown', state.editor.keyHandler);
    }
    try { state.editor.canvas.dispose(); } catch (error) { /* ignore */ }
  }
  state.editor = null;
}

function openImageEditor(rel, options = {}) {
  disposeImageEditor();
  const fromRaw = options.fromRaw === true;
  const name = rel.split('/').pop();
  openModal({
    title: (fromRaw ? '编辑原图 · ' : '图片编辑 · ') + name,
    className: 'wide',
    body: `
      <div class="studio-layout">
        <div class="studio-left">
          <div class="editor-group-title">素材库</div>
          <div class="editor-mode-row">
            <button type="button" class="btn btn-sm editor-mode active" data-editor-mode="add">加入画布</button>
            <button type="button" class="btn btn-sm editor-mode" data-editor-mode="replace">替换选中</button>
            <button type="button" class="btn btn-sm editor-mode" data-editor-mode="base">替换底图</button>
          </div>
          <div class="small muted mt-8" id="editorModeHint">点击素材加入画布；选中图片后可切换为“替换选中”。</div>
          <div class="row mt-8">
            <button type="button" class="btn btn-sm btn-secondary" id="edUploadBtn">上传本地图片</button>
            <input type="file" id="edUploadInput" accept="image/*" class="hidden">
          </div>
          <div class="studio-library" id="studioLibrary">
            ${[['main', '主图'], ['detail', '详情'], ['sku', 'SKU'], ['review', '待确认']].map(([kind, label]) => {
              const files = state.raw[kind] || [];
              if (!files.length) return '';
              return `<div class="small muted mt-8">${label}</div><div class="source-grid">
                ${files.map((file) => `<button type="button" class="source-item" data-add-image="${esc(file)}" title="${esc(file)}">
                  <img src="${currentMedia(file, 100)}" alt=""><span>${esc(file.split('/').pop())}</span>
                </button>`).join('')}</div>`;
            }).join('') || '<div class="small muted">暂无素材</div>'}
          </div>
        </div>
        <div class="studio-center">
          <div class="editor-toolbar row">
            <button type="button" class="btn btn-sm editor-tool active" data-tool="select">选择</button>
            <button type="button" class="btn btn-sm editor-tool" data-tool="text">文字</button>
            <button type="button" class="btn btn-sm editor-tool" data-tool="draw">画笔</button>
            <button type="button" class="btn btn-sm editor-tool" data-tool="crop">裁剪</button>
            <button type="button" class="btn btn-sm" data-op="fit">适应画布</button>
            <button type="button" class="btn btn-sm" data-op="center">居中</button>
            <button type="button" class="btn btn-sm" data-op="rotate">旋转90°</button>
            <button type="button" class="btn btn-sm" data-op="flipx">翻转</button>
            <button type="button" class="btn btn-sm" data-op="stitchH">横向拼接</button>
            <button type="button" class="btn btn-sm" data-op="stitchV">纵向拼接</button>
            <button type="button" class="btn btn-sm" data-op="stitchGrid">九宫格</button>
            <button type="button" class="btn btn-sm" data-op="cutout">一键抠图</button>
            <button type="button" class="btn btn-sm" data-op="undo">撤销</button>
            <button type="button" class="btn btn-sm" data-op="redo">重做</button>
          </div>
          <div class="editor-canvas-wrap"><canvas id="editorCanvas"></canvas></div>
          <div class="row mt-8">
            <label class="field" style="margin:0"><span>文字内容</span><input id="edText" value="输入文字" style="width:180px"></label>
            <label class="field" style="margin:0"><span>颜色</span><input type="color" id="edTextColor" value="#ffffff" style="width:64px"></label>
            <label class="field" style="margin:0"><span>字号</span><input type="number" id="edTextSize" value="48" style="width:76px"></label>
            <label class="checkbox"><input type="checkbox" id="edTextBold" checked> 加粗</label>
            <label class="field" style="margin:0"><span>画笔颜色</span><input type="color" id="edBrushColor" value="#e8467c" style="width:64px"></label>
            <label class="field" style="margin:0"><span>画笔粗细</span><input type="number" id="edBrushWidth" value="6" style="width:70px"></label>
          </div>
          <button type="button" class="btn btn-primary btn-sm mt-8 hidden" id="edApplyCrop">应用裁剪</button>
        </div>
        <div class="studio-right">
          <div class="editor-group-title">属性 / 图层</div>
          <div id="studioProps"></div>
          <div class="editor-group mt-12">
            <div class="editor-group-title">调色</div>
            <label class="field"><span>亮度 <b id="edBrightnessVal">0</b></span><input type="range" id="edBrightness" min="-100" max="100" value="0"></label>
            <label class="field"><span>对比度 <b id="edContrastVal">0</b></span><input type="range" id="edContrast" min="-100" max="100" value="0"></label>
            <label class="field"><span>饱和度 <b id="edSaturationVal">0</b></span><input type="range" id="edSaturation" min="-100" max="100" value="0"></label>
          </div>
          <div class="editor-group mt-12">
            <label class="field"><span>画布底色</span><input type="color" id="edCanvasBg" value="#ffffff"></label>
            <label class="field"><span>文件名备注（可选）</span><input id="edNote" placeholder="例如：改动文字"></label>
            <div class="small muted">提示：拖动画布中的图片可移动，拖动角点可缩放；所有编辑结果统一保存到 output/edited，按文件名区分。</div>
          </div>
          <div id="studioLayers" class="mt-8"></div>
        </div>
      </div>`,
    foot: `
      <button class="btn" id="edCancel">取消</button>
      ${fromRaw ? '' : '<button class="btn btn-secondary" id="edSaveAs">另存为新图</button>'}
      <button class="btn btn-primary" id="edSave">${fromRaw ? '保存到编辑文件夹' : '保存覆盖'}</button>`,
    onMount: (root) => {
      const canvas = new fabric.Canvas('editorCanvas', { backgroundColor: '#ffffff', preserveObjectStacking: true });
      state.editor = {
        canvas, rel, fromRaw, history: [], index: -1, tool: 'select',
        cropRect: null, filterTimer: null, libraryMode: 'add', keyHandler: null,
      };
      fabric.Image.fromURL(currentMedia(rel), (image) => {
        canvas.setWidth(image.width || 800);
        canvas.setHeight(image.height || 800);
        image.set({ selectable: true });
        image.sourceFile = rel;
        canvas.add(image);
        canvas.renderAll();
        api(taskUrl('/design')).then((saved) => {
          const design = saved.design || {};
          if (design.editorSource === rel && design.fabric && Array.isArray(design.fabric.objects) && design.fabric.objects.length) {
            canvas.loadFromJSON(design.fabric, () => {
              canvas.getObjects().forEach((object) => {
                if (object.sourceFile) object.set({ sourceFile: object.sourceFile });
              });
              canvas.renderAll();
              editorSnapshot();
              editorRefreshProps();
            });
          } else {
            editorSnapshot();
            editorRefreshProps();
          }
        }).catch(() => { editorSnapshot(); editorRefreshProps(); });
      });
      canvas.on('path:created', () => editorSnapshot());
      canvas.on('selection:created', editorRefreshProps);
      canvas.on('selection:updated', editorRefreshProps);
      canvas.on('selection:cleared', editorRefreshProps);
      canvas.on('object:modified', () => { editorSnapshot(); editorRefreshProps(); });
      $$('[data-add-image]', root).forEach((button) => {
        button.onclick = () => editorUseLibraryImage(button.dataset.addImage);
      });
      $$('[data-editor-mode]', root).forEach((button) => {
        button.onclick = () => {
          $$('[data-editor-mode]', root).forEach((item) => item.classList.remove('active'));
          button.classList.add('active');
          state.editor.libraryMode = button.dataset.editorMode;
          const hints = {
            add: '点击素材加入画布；选中图片后可切换为“替换选中”。',
            replace: '先在画布中选中一张图片，再点击左侧素材即可替换，位置、大小和角度保持不变。',
            base: '点击素材替换最底层的商品图，其他文字和装饰保持不变。',
          };
          $('#editorModeHint').textContent = hints[state.editor.libraryMode] || '';
        };
      });
      $('#edUploadBtn').onclick = () => $('#edUploadInput').click();
      $('#edUploadInput').onchange = async () => {
        const input = $('#edUploadInput');
        if (!input.files || !input.files.length) return;
        try {
          const files = await uploadTaskFiles(input.files, 'main');
          if (files.length) {
            await refreshTask();
            editorUseLibraryImage(files[0]);
            toast(`已上传并${state.editor.libraryMode === 'add' ? '加入' : '替换'}：${files[0].split('/').pop()}`, 'success');
          }
        } catch (error) {
          toast(error.message, 'error');
        } finally {
          input.value = '';
        }
      };
      canvas.on('mouse:down', (event) => {
        if (state.editor.tool !== 'text') return;
        if (event.target && event.target.type === 'textbox') return;
        const text = new fabric.Textbox($('#edText').value || '输入文字', {
          left: event.pointer.x,
          top: event.pointer.y,
          fill: $('#edTextColor').value,
          fontSize: parseInt($('#edTextSize').value, 10) || 48,
          fontWeight: $('#edTextBold').checked ? 'bold' : 'normal',
          width: 360,
          shadow: new fabric.Shadow({ color: 'rgba(0,0,0,0.35)', blur: 4, offsetX: 1, offsetY: 1 }),
        });
        canvas.add(text);
        canvas.setActiveObject(text);
        canvas.renderAll();
        editorSnapshot();
      });
      $$('.editor-tool', root).forEach((button) => {
        button.onclick = () => {
          $$('.editor-tool', root).forEach((item) => item.classList.remove('active'));
          button.classList.add('active');
          state.editor.tool = button.dataset.tool;
          canvas.isDrawingMode = state.editor.tool === 'draw';
          if (canvas.isDrawingMode) {
            canvas.freeDrawingBrush = new fabric.PencilBrush(canvas);
            canvas.freeDrawingBrush.color = $('#edBrushColor').value;
            canvas.freeDrawingBrush.width = parseInt($('#edBrushWidth').value, 10) || 6;
          }
          if (state.editor.tool === 'crop') {
            const width = canvas.getWidth();
            const height = canvas.getHeight();
            const rect = new fabric.Rect({
              left: width * 0.15, top: height * 0.15,
              width: width * 0.7, height: height * 0.7,
              fill: 'transparent', stroke: '#e8467c', strokeWidth: 2,
              strokeDashArray: [8, 4], cornerColor: '#e8467c', cornerSize: 12,
              transparentCorners: false,
            });
            canvas.add(rect);
            canvas.setActiveObject(rect);
            canvas.renderAll();
            state.editor.cropRect = rect;
            $('#edApplyCrop').classList.remove('hidden');
          } else {
            $('#edApplyCrop').classList.add('hidden');
          }
        };
      });
      $$('[data-op]', root).forEach((button) => {
        button.onclick = () => {
          const op = button.dataset.op;
          if (op === 'undo') return editorUndo();
          if (op === 'redo') return editorRedo();
          if (op === 'fit') return editorFitObject();
          if (op === 'center') return editorCenterObject();
          if (op === 'rotate') return editorTransform(-90, false, false);
          if (op === 'flipx') return editorTransform(0, true, false);
          if (op === 'flipy') return editorTransform(0, false, true);
          if (op === 'stitchH') return editorStitch('h');
          if (op === 'stitchV') return editorStitch('v');
          if (op === 'stitchGrid') return editorStitch('grid');
          if (op === 'cutout') return editorCutout();
        };
      });
      $('#edApplyCrop').onclick = applyEditorCrop;
      $('#edCanvasBg').onchange = () => {
        state.editor.canvas.backgroundColor = $('#edCanvasBg').value;
        state.editor.canvas.renderAll();
        editorSnapshot();
      };
      ['Brightness', 'Contrast', 'Saturation'].forEach((key) => {
        const slider = $('#ed' + key);
        slider.oninput = () => {
          $('#ed' + key + 'Val').textContent = slider.value;
          editorApplyFilters();
          clearTimeout(state.editor.filterTimer);
          state.editor.filterTimer = setTimeout(editorSnapshot, 220);
        };
      });
      $('#edSave').onclick = () => saveImageEdit(fromRaw ? true : false);
      if ($('#edSaveAs')) $('#edSaveAs').onclick = () => saveImageEdit(true);

      const keyHandler = (event) => {
        if (event.target && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
          event.preventDefault();
          if (event.shiftKey) editorRedo();
          else editorUndo();
          return;
        }
        if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'y') {
          event.preventDefault();
          editorRedo();
          return;
        }
        const active = canvas.getActiveObject();
        if (!active) return;
        if (event.key === 'Delete' || event.key === 'Backspace') {
          event.preventDefault();
          canvas.remove(active);
          canvas.discardActiveObject();
          canvas.renderAll();
          editorSnapshot();
          editorRefreshProps();
          return;
        }
        const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
        const delta = arrows[event.key];
        if (delta) {
          event.preventDefault();
          const step = event.shiftKey ? 10 : 1;
          active.set({ left: (active.left || 0) + delta[0] * step, top: (active.top || 0) + delta[1] * step });
          active.setCoords();
          canvas.renderAll();
          editorSnapshot();
        }
      };
      state.editor.keyHandler = keyHandler;
      document.addEventListener('keydown', keyHandler);
      $('#edCancel').onclick = () => { disposeImageEditor(); closeModal(); };
      $('.modal-close', root).onclick = () => { disposeImageEditor(); closeModal(); };
      $('.modal-backdrop', root).addEventListener('click', (event) => {
        if (event.target === $('.modal-backdrop', root)) { disposeImageEditor(); closeModal(); }
      });
    },
  });
}

async function uploadTaskFiles(files, kind = 'main') {
  const form = new FormData();
  form.append('kind', kind);
  Array.from(files).forEach((file) => form.append('files', file));
  const response = await fetch(taskUrl('/upload'), { method: 'POST', body: form });
  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw new Error('上传响应格式错误');
  }
  if (!response.ok || !data.ok) throw new Error(data.error || '上传失败');
  return data.data.files || [];
}

function editorUseLibraryImage(rel) {
  const editor = state.editor;
  if (!editor) return;
  if (editor.libraryMode === 'replace') {
    editorReplaceImage(rel, false);
    return;
  }
  if (editor.libraryMode === 'base') {
    editorReplaceImage(rel, true);
    return;
  }
  editorAddImage(rel);
}

function editorReplaceImage(rel, asBase) {
  const editor = state.editor;
  if (!editor) return;
  const canvas = editor.canvas;
  const objects = canvas.getObjects();
  const target = asBase
    ? objects.find((item) => item.type === 'image')
    : canvas.getActiveObject();
  if (!asBase && (!target || target.type !== 'image')) {
    toast('请先在画布中选中一张图片，再点击左侧素材替换', 'error');
    return;
  }
  fabric.Image.fromURL(currentMedia(rel), (image) => {
    let index = 0;
    if (target) {
      index = Math.max(0, canvas.getObjects().indexOf(target));
      image.set({
        left: target.left,
        top: target.top,
        scaleX: target.scaleX,
        scaleY: target.scaleY,
        angle: target.angle,
        opacity: target.opacity,
      });
      canvas.remove(target);
    } else {
      const limit = Math.min(canvas.getWidth(), canvas.getHeight()) * 0.72;
      const scale = Math.min(limit / (image.width || 1), limit / (image.height || 1), 1);
      image.set({
        left: (canvas.getWidth() - (image.width || 1) * scale) / 2,
        top: (canvas.getHeight() - (image.height || 1) * scale) / 2,
        scaleX: scale,
        scaleY: scale,
      });
    }
    image.sourceFile = rel;
    canvas.insertAt(image, Math.min(index, canvas.getObjects().length));
    if (asBase && !target) canvas.moveTo(image, 0);
    canvas.setActiveObject(image);
    canvas.renderAll();
    editorSnapshot();
    editorRefreshProps();
    toast(asBase ? '已替换底图' : '已替换选中图片', 'success');
  });
}

function editorFitObject() {
  const editor = state.editor;
  if (!editor) return;
  const canvas = editor.canvas;
  const object = canvas.getActiveObject();
  if (!object) {
    toast('请先选中需要调整的图片或文字', 'error');
    return;
  }
  const baseWidth = object.width || 1;
  const baseHeight = object.height || 1;
  const scale = Math.min(canvas.getWidth() / baseWidth, canvas.getHeight() / baseHeight);
  object.set({ scaleX: scale, scaleY: scale, angle: 0 });
  object.setCoords();
  editorCenterObject(true);
}

function editorCenterObject(silent = false) {
  const editor = state.editor;
  if (!editor) return;
  const canvas = editor.canvas;
  const object = canvas.getActiveObject();
  if (!object) {
    if (!silent) toast('请先选中需要居中的对象', 'error');
    return;
  }
  object.set({
    left: (canvas.getWidth() - object.getScaledWidth()) / 2,
    top: (canvas.getHeight() - object.getScaledHeight()) / 2,
  });
  object.setCoords();
  canvas.renderAll();
  editorSnapshot();
  editorRefreshProps();
}


function editorRefreshProps() {
  const editor = state.editor;
  const props = $('#studioProps');
  const layers = $('#studioLayers');
  if (!editor || !props || !layers) return;
  const canvas = editor.canvas;
  const object = canvas.getActiveObject();
  let html = '';
  if (!object) {
    html = '<div class="small muted">未选中对象。点击画布里的文字或图片即可移动、缩放。</div>';
  } else if (object.type === 'textbox' || object.type === 'text') {
    html = `
      <label class="field"><span>文字内容</span><textarea id="propText" rows="2">${esc(object.text || '')}</textarea></label>
      <label class="field"><span>文字颜色</span><input type="color" id="propColor" value="${esc(object.fill || '#ffffff')}"></label>
      <label class="field"><span>字号</span><input type="number" id="propSize" value="${object.fontSize || 48}"></label>
      <div class="row"><button class="btn btn-sm" id="propBold">加粗切换</button><button class="btn btn-sm" data-layer="delete">删除</button></div>`;
  } else {
    html = `
      <div class="small muted">来源：${esc(object.sourceFile || '画布元素')}</div>
      <label class="field"><span>透明度 <b id="propOpacityVal">${Math.round((object.opacity ?? 1) * 100)}</b></span><input type="range" id="propOpacity" min="0" max="100" value="${Math.round((object.opacity ?? 1) * 100)}"></label>
      <label class="field"><span>大小 <b id="propScaleVal">${Math.round((object.scaleX || 1) * 100)}%</b></span><input type="range" id="propScale" min="10" max="300" value="${Math.round((object.scaleX || 1) * 100)}"></label>
      <div class="row">
        <button class="btn btn-sm" id="propFit">适应画布</button>
        <button class="btn btn-sm" id="propCenter">居中</button>
      </div>
      <div class="row mt-8">
        <button class="btn btn-sm" data-layer="up">上移一层</button>
        <button class="btn btn-sm" data-layer="down">下移一层</button>
        <button class="btn btn-sm" data-layer="top">置顶</button>
        <button class="btn btn-sm" data-layer="bottom">置底</button>
        <button class="btn btn-sm btn-danger" data-layer="delete">删除</button>
      </div>
      <button class="btn btn-secondary btn-sm mt-8" id="propReplace">替换这张图片</button>
      <button class="btn btn-secondary btn-sm mt-8" id="propCutout">抠掉背景</button>`;
  }
  props.innerHTML = html;
  const objects = canvas.getObjects();
  layers.innerHTML = `<div class="editor-group-title">图层</div><div class="row">${objects.map((item, index) => `
    <button class="btn btn-sm ${item === object ? 'btn-secondary' : ''}" data-layer-select="${index}">${index + 1}. ${item.type === 'image' ? '图片' : (item.type === 'textbox' ? '文字' : '元素')}</button>`).join('')}</div>`;

  const shortcut = (callback) => {
    clearTimeout(editor.propertyTimer);
    editor.propertyTimer = setTimeout(() => { callback(); editorSnapshot(); }, 180);
  };
  if (object && (object.type === 'textbox' || object.type === 'text')) {
    $('#propText').oninput = (event) => shortcut(() => object.set('text', event.target.value));
    $('#propColor').onchange = (event) => shortcut(() => object.set('fill', event.target.value));
    $('#propSize').oninput = (event) => shortcut(() => object.set('fontSize', parseInt(event.target.value, 10) || 48));
    $('#propBold').onclick = () => shortcut(() => object.set('fontWeight', object.fontWeight === 'bold' ? 'normal' : 'bold'));
  } else if (object) {
    $('#propOpacity').oninput = (event) => {
      $('#propOpacityVal').textContent = event.target.value;
      shortcut(() => object.set('opacity', parseInt(event.target.value, 10) / 100));
    };
    $('#propScale').oninput = (event) => {
      $('#propScaleVal').textContent = event.target.value + '%';
      const scale = parseInt(event.target.value, 10) / 100;
      shortcut(() => object.set({ scaleX: scale, scaleY: scale }));
    };
    if ($('#propFit')) $('#propFit').onclick = () => editorFitObject();
    if ($('#propCenter')) $('#propCenter').onclick = () => editorCenterObject();
    if ($('#propReplace')) {
      $('#propReplace').onclick = () => {
        const button = $('[data-editor-mode="replace"]');
        if (button) button.click();
        $('#editorModeHint').textContent = '已进入替换模式：点击左侧任意图片，即可替换当前选中的图片。';
      };
    }
    if ($('#propCutout')) $('#propCutout').onclick = () => editorCutout();
  }
  $$('[data-layer]', props).forEach((button) => {
    button.onclick = () => {
      const action = button.dataset.layer;
      if (action === 'delete') canvas.remove(object);
      else if (action === 'up') canvas.bringObjectForward(object);
      else if (action === 'down') canvas.sendObjectBackwards(object);
      else if (action === 'top') canvas.bringObjectToFront(object);
      else if (action === 'bottom') canvas.sendObjectToBack(object);
      canvas.discardActiveObject();
      canvas.renderAll();
      editorSnapshot();
      editorRefreshProps();
    };
  });
  $$('[data-layer-select]', layers).forEach((button) => {
    button.onclick = () => {
      const index = parseInt(button.dataset.layerSelect, 10);
      canvas.setActiveObject(objects[index]);
      canvas.renderAll();
      editorRefreshProps();
    };
  });
}

function editorAddImage(rel) {
  const editor = state.editor;
  if (!editor) return;
  const canvas = editor.canvas;
  fabric.Image.fromURL(currentMedia(rel), (image) => {
    const limit = Math.min(canvas.getWidth(), canvas.getHeight()) * 0.55;
    const scale = Math.min(limit / (image.width || 1), limit / (image.height || 1), 1);
    image.set({
      left: (canvas.getWidth() - image.width * scale) / 2,
      top: (canvas.getHeight() - image.height * scale) / 2,
      scaleX: scale,
      scaleY: scale,
    });
    image.sourceFile = rel;
    canvas.add(image);
    canvas.setActiveObject(image);
    canvas.renderAll();
    editorSnapshot();
    editorRefreshProps();
  });
}

async function editorStitch(layout) {
  const editor = state.editor;
  if (!editor) return;
  const count = layout === 'grid' ? 4 : 2;
  let files = (state.raw.main || []).slice(0, count);
  if (files.length < count) files = files.concat((state.raw.sku || []).slice(0, count - files.length));
  if (files.length < count) files = files.concat((state.raw.detail || []).slice(0, count - files.length));
  if (files.length < count) { toast('可用素材不足，无法拼接', 'error'); return; }
  const images = await Promise.all(files.map((file) => new Promise((resolve) => {
    fabric.Image.fromURL(currentMedia(file, 800), (image) => resolve({ image, file }));
  })));
  const canvas = editor.canvas;
  let cellW = Math.max(...images.map((item) => item.image.width));
  let cellH = Math.max(...images.map((item) => item.image.height));
  const cols = layout === 'h' ? images.length : layout === 'grid' ? 2 : 1;
  const rows = layout === 'v' ? images.length : layout === 'grid' ? 2 : 1;
  const scale = Math.min(1, 900 / (cellW * cols), 900 / (cellH * rows));
  cellW = Math.round(cellW * scale);
  cellH = Math.round(cellH * scale);
  canvas.clear();
  canvas.setWidth(cellW * cols);
  canvas.setHeight(cellH * rows);
  images.forEach((item, index) => {
    const image = item.image;
    const col = index % cols;
    const row = Math.floor(index / cols);
    image.set({
      left: col * cellW,
      top: row * cellH,
      scaleX: (cellW / (image.width || 1)) * scale,
      scaleY: (cellH / (image.height || 1)) * scale,
      selectable: true,
    });
    image.sourceFile = item.file;
    canvas.add(image);
  });
  canvas.renderAll();
  editorSnapshot();
  editorRefreshProps();
}

async function editorCutout() {
  const editor = state.editor;
  if (!editor) return;
  const object = editor.canvas.getActiveObject();
  if (!object || object.type !== 'image' || !object.sourceFile) {
    toast('请先选中一张来源于素材库的图片', 'error');
    return;
  }
  try {
    const result = await api(taskUrl('/image/remove-bg'), {
      method: 'POST',
      json: { file: object.sourceFile, tolerance: 36 },
    });
    object.setSrc(currentMedia(result.file), () => {
      object.sourceFile = result.file;
      editor.canvas.renderAll();
      editorSnapshot();
      editorRefreshProps();
      toast('已去除背景，复杂背景请人工细修', 'success');
    });
  } catch (error) {
    toast(error.message, 'error');
  }
}

function editorSnapshot() {
  const editor = state.editor;
  if (!editor || !editor.canvas) return;
  const json = JSON.stringify(editor.canvas.toJSON(['sourceFile']));
  editor.history = editor.history.slice(0, editor.index + 1);
  editor.history.push(json);
  if (editor.history.length > 30) editor.history.shift();
  editor.index = editor.history.length - 1;
}

function editorDesignPayload() {
  const editor = state.editor;
  if (!editor || !editor.canvas) return null;
  const serialized = editor.canvas.toJSON(['sourceFile']);
  const layers = (serialized.objects || []).map((object, index) => ({
    id: object.id || `layer-${index + 1}`,
    type: object.type,
    source: object.sourceFile || '',
    content: object.text || '',
    left: Number(object.left || 0),
    top: Number(object.top || 0),
    width: Number(object.width || 0),
    height: Number(object.height || 0),
    scaleX: Number(object.scaleX || 1),
    scaleY: Number(object.scaleY || 1),
    angle: Number(object.angle || 0),
    opacity: Number(object.opacity == null ? 1 : object.opacity),
    fill: object.fill || '',
    fontSize: Number(object.fontSize || 0),
    fontFamily: object.fontFamily || '',
  }));
  return {
    editorSource: editor.rel,
    canvas: { width: Number(editor.canvas.getWidth()), height: Number(editor.canvas.getHeight()) },
    background: editor.canvas.backgroundColor || '#ffffff',
    layers,
    fabric: serialized,
  };
}

function editorRestore() {
  const editor = state.editor;
  if (!editor || editor.index < 0 || !editor.history[editor.index]) return;
  editor.canvas.loadFromJSON(editor.history[editor.index], () => {
    editor.canvas.renderAll();
    editorApplyFilters();
    editorRefreshProps();
  });
}

function editorUndo() {
  const editor = state.editor;
  if (!editor || editor.index <= 0) return;
  editor.index -= 1;
  editorRestore();
}

function editorRedo() {
  const editor = state.editor;
  if (!editor || editor.index >= editor.history.length - 1) return;
  editor.index += 1;
  editorRestore();
}

function editorApplyFilters() {
  const editor = state.editor;
  if (!editor) return;
  const brightness = parseInt($('#edBrightness').value, 10) / 100;
  const contrast = parseInt($('#edContrast').value, 10) / 100;
  const saturation = parseInt($('#edSaturation').value, 10) / 100;
  editor.canvas.getObjects().forEach((object) => {
    if (object.type !== 'image') return;
    object.filters = [];
    if (brightness) object.filters.push(new fabric.Image.filters.Brightness({ brightness }));
    if (contrast) object.filters.push(new fabric.Image.filters.Contrast({ contrast }));
    if (saturation) object.filters.push(new fabric.Image.filters.Saturation({ saturation }));
    object.applyFilters();
  });
  editor.canvas.renderAll();
}

function editorTransform(angle, flipX, flipY) {
  const editor = state.editor;
  if (!editor) return;
  const canvas = editor.canvas;
  const object = canvas.getActiveObject();
  if (object && object.type === 'image') {
    if (angle) object.rotate((object.angle || 0) + angle);
    if (flipX) object.set('flipX', !object.flipX);
    if (flipY) object.set('flipY', !object.flipY);
    object.setCoords();
    canvas.renderAll();
    editorSnapshot();
    editorRefreshProps();
    return;
  }
  const data = canvas.toDataURL({ format: 'png' });
  const image = new Image();
  image.onload = () => {
    const offscreen = document.createElement('canvas');
    offscreen.width = angle ? image.height : image.width;
    offscreen.height = angle ? image.width : image.height;
    const context = offscreen.getContext('2d');
    context.translate(offscreen.width / 2, offscreen.height / 2);
    if (angle) context.rotate(angle * Math.PI / 180);
    if (flipX) context.scale(-1, 1);
    if (flipY) context.scale(1, -1);
    context.drawImage(image, -image.width / 2, -image.height / 2);
    fabric.Image.fromURL(offscreen.toDataURL('image/png'), (result) => {
      canvas.clear();
      canvas.setWidth(offscreen.width);
      canvas.setHeight(offscreen.height);
      canvas.add(result);
      canvas.renderAll();
      editorSnapshot();
    });
  };
  image.src = data;
}

function applyEditorCrop() {
  const editor = state.editor;
  if (!editor || !editor.cropRect) return;
  const rect = editor.cropRect;
  const left = Math.max(0, Math.round(rect.left));
  const top = Math.max(0, Math.round(rect.top));
  const width = Math.max(10, Math.round(rect.width * (rect.scaleX || 1)));
  const height = Math.max(10, Math.round(rect.height * (rect.scaleY || 1)));
  editor.canvas.remove(rect);
  editor.cropRect = null;
  $('#edApplyCrop').classList.add('hidden');
  const data = editor.canvas.toDataURL({ format: 'png' });
  const image = new Image();
  image.onload = () => {
    const offscreen = document.createElement('canvas');
    offscreen.width = width;
    offscreen.height = height;
    offscreen.getContext('2d').drawImage(image, -left, -top);
    fabric.Image.fromURL(offscreen.toDataURL('image/png'), (result) => {
      editor.canvas.clear();
      editor.canvas.setWidth(width);
      editor.canvas.setHeight(height);
      editor.canvas.add(result);
      editor.canvas.renderAll();
      editorSnapshot();
    });
  };
  image.src = data;
}

async function saveImageEdit(saveAsNew) {
  const editor = state.editor;
  if (!editor) return;
  try {
    const button = saveAsNew ? $('#edSaveAs') : $('#edSave');
    if (button) {
      button.disabled = true;
      button.textContent = '保存中…';
    }
    const dataUrl = editor.canvas.toDataURL({ format: 'png' });
    const result = await api(taskUrl('/image/edit'), {
      method: 'POST',
      json: {
        file: editor.rel,
        dataUrl,
        saveAsNew: editor.fromRaw ? true : saveAsNew,
        note: $('#edNote') ? $('#edNote').value.trim() : '',
      },
    });
    const design = editorDesignPayload();
    if (design) {
      await api(taskUrl('/design'), {
        method: 'POST',
        json: { design, note: $('#edNote') ? $('#edNote').value.trim() : '画布编辑' },
      });
    }
    disposeImageEditor();
    closeModal();
    toast(`已保存到统一编辑文件夹：${result.file.split('/').pop()}`, 'success');
    await refreshTask();
  } catch (error) {
    const button = saveAsNew ? $('#edSaveAs') : $('#edSave');
    if (button) {
      button.disabled = false;
      button.textContent = saveAsNew && !editor.fromRaw ? '另存为新图' : (editor.fromRaw ? '保存到编辑文件夹' : '保存覆盖');
    }
    toast(error.message, 'error');
  }
}

function viewOutputs(kind) {
  const labels = {
    main_pc: '电脑端主图', main_mobile: '手机端主图', detail: '详情页图',
    sku: 'SKU 图', white: '白底图', edited: '编辑成品',
  };
  const groups = kind === 'main' ? ['main_pc', 'main_mobile'] : [kind];
  const items = [];
  groups.forEach((group) => {
    (state.outputs[group] || []).forEach((file) => items.push({ group, file }));
  });
  if (!items.length) {
    toast('还没有生成该类型的成品，请先点“生成并查看”', 'error');
    return;
  }
  openModal({
    title: '查看修改后的图片',
    className: 'wide',
    body: `
      <div class="gallery-grid">
        ${items.map((item) => `
          <div class="gallery-item">
            <img src="${currentMedia(item.file, 360)}" data-gallery="${esc(item.file)}" alt="">
            <span>${esc(labels[item.group] || item.group)}</span>
          </div>`).join('')}
      </div>`,
    foot: '<button class="btn" id="galleryClose">返回继续调整</button>',
    onMount: (root) => {
      $('#galleryClose', root).onclick = closeModal;
      $$('[data-gallery]', root).forEach((image) => {
        image.onclick = () => openLightbox(image.dataset.gallery);
      });
    },
  });
}

function renderRaw() {
  const kinds = [
    ['main', '主图'], ['detail', '详情图'], ['sku', 'SKU 图'], ['video', '视频'], ['review', '待确认'],
  ];
  const files = state.raw[state.rawKind] || [];
  const cards = files.map((rel, index) => {
    const name = rel.split('/').pop();
    const isVideo = state.rawKind === 'video';
    const canSelect = state.rawKind === 'detail';
    const needsReview = state.rawKind === 'review';
    const canEdit = !isVideo;
    const checked = state.detailSelection.has(rel) ? 'checked' : '';
    return `
      <div class="thumb-item ${checked ? 'selected' : ''}" data-rel="${esc(rel)}">
        ${canSelect ? `<label class="thumb-check"><input type="checkbox" class="detail-check" data-rel="${esc(rel)}" ${checked}> 选用</label>` : ''}
        <label class="raw-delete-check"><input type="checkbox" class="raw-delete-input" data-delete-file="${esc(rel)}"> 选择删除</label>
        ${canEdit ? `<button type="button" class="btn btn-sm raw-edit-btn" data-edit-raw="${esc(rel)}">编辑</button>` : ''}
        ${isVideo
          ? `<div style="height:128px;display:flex;align-items:center;justify-content:center;background:#111;color:#fff;font-size:12px">视频文件</div>`
          : `<img src="${currentMedia(rel, 220)}" alt="" class="raw-thumb">`}
        <div class="thumb-name" title="${esc(rel)}">${index + 1}. ${esc(name)}</div>
        ${needsReview ? `
          <div class="review-actions">
            <select class="review-target" aria-label="素材归类">
              <option value="main">主图</option>
              <option value="detail">详情图</option>
              <option value="sku">SKU 图</option>
            </select>
            <input class="review-name" type="text" placeholder="SKU 名称（可选）" aria-label="SKU 名称">
            <button type="button" class="btn btn-sm btn-secondary" data-classify-review="${esc(rel)}">确认归类</button>
          </div>` : ''}
      </div>`;
  }).join('');
  $('#panel-raw').innerHTML = `
    <div class="card">
      <div class="card-head">
        <h3>原始素材 <span class="sub">按目录归档，原图只读保留</span></h3>
        <button class="btn btn-sm" id="openRawFolder">打开 raw 文件夹</button>
      </div>
      <div class="card-body">
        <div class="kind-bar">
          ${kinds.map(([key, label]) => `<button class="kind-btn ${state.rawKind === key ? 'active' : ''}" data-kind="${key}">${label} (${(state.raw[key] || []).length})</button>`).join('')}
        </div>
        <div class="row" style="margin-bottom:14px">
          <select id="uploadKind" style="width:140px">
            ${kinds.map(([key, label]) => `<option value="${key}" ${key === state.rawKind ? 'selected' : ''}>${label}</option>`).join('')}
          </select>
          <input type="file" id="uploadFiles" multiple accept="image/*,video/*" style="max-width:320px">
          <button class="btn btn-primary btn-sm" id="uploadBtn">上传图片</button>
          <span class="small muted">手动新建任务后，可在此上传图片</span>
        </div>
        ${state.raw.review && state.raw.review.length
          ? '<div class="alert alert-warn">这些图片未能从网页数据中确定用途，尚未归入主图或详情图。逐张预览后再归类，可避免把广告图误当商品素材。</div>'
          : ''}
        ${files.length ? `
          <div class="row raw-bulk-toolbar">
            <label class="checkbox"><input type="checkbox" id="selectAllRaw"> 全选当前分类</label>
            <button type="button" class="btn btn-sm btn-danger" id="deleteSelectedRaw" disabled>删除所选素材（0）</button>
          </div>
          <div class="thumb-grid">${cards}</div>`
          : '<div class="alert alert-info">该分类暂无素材。直采失败时可手动上传，或改用导入文件夹。</div>'}
      </div>
    </div>`;
  $$('.kind-btn', $('#panel-raw')).forEach((button) => {
    button.onclick = () => {
      state.rawKind = button.dataset.kind;
      renderRaw();
    };
  });
  const rawDeleteChecks = $$('.raw-delete-input', $('#panel-raw'));
  if (rawDeleteChecks.length) {
    const selectAll = $('#selectAllRaw');
    const deleteSelected = $('#deleteSelectedRaw');
    const updateSelectionCount = () => {
      const selectedCount = rawDeleteChecks.filter((checkbox) => checkbox.checked).length;
      deleteSelected.textContent = `删除所选素材（${selectedCount}）`;
      deleteSelected.disabled = selectedCount === 0;
      selectAll.checked = selectedCount === rawDeleteChecks.length;
      selectAll.indeterminate = selectedCount > 0 && selectedCount < rawDeleteChecks.length;
    };
    rawDeleteChecks.forEach((checkbox) => {
      checkbox.onchange = updateSelectionCount;
    });
    selectAll.onchange = () => {
      rawDeleteChecks.forEach((checkbox) => { checkbox.checked = selectAll.checked; });
      updateSelectionCount();
    };
    deleteSelected.onclick = async () => {
      const filesToDelete = rawDeleteChecks
        .filter((checkbox) => checkbox.checked)
        .map((checkbox) => checkbox.dataset.deleteFile);
      if (!filesToDelete.length) return;
      if (!confirm(`确定删除选中的 ${filesToDelete.length} 个原始素材吗？此操作不可恢复。`)) return;
      deleteSelected.disabled = true;
      let deletedCount = 0;
      for (const file of filesToDelete) {
        try {
          await api(taskUrl('/raw'), { method: 'DELETE', json: { file } });
          state.detailSelection.delete(file);
          deletedCount += 1;
        } catch (error) {
          toast(`已删除 ${deletedCount} 项，删除失败：${error.message}`, 'error');
          await refreshTask();
          return;
        }
      }
      toast(`已删除 ${filesToDelete.length} 个素材`, 'success');
      await refreshTask();
    };
  }
  $$('.raw-thumb', $('#panel-raw')).forEach((image) => {
    image.onclick = () => openLightbox(image.closest('.thumb-item').dataset.rel);
  });
  $$('[data-edit-raw]', $('#panel-raw')).forEach((button) => {
    button.onclick = (event) => {
      event.stopPropagation();
      openImageEditor(button.dataset.editRaw, { fromRaw: true });
    };
  });
  $$('.detail-check', $('#panel-raw')).forEach((checkbox) => {
    checkbox.onchange = () => {
      if (checkbox.checked) state.detailSelection.add(checkbox.dataset.rel);
      else state.detailSelection.delete(checkbox.dataset.rel);
      checkbox.closest('.thumb-item').classList.toggle('selected', checkbox.checked);
    };
  });
  $$('[data-classify-review]', $('#panel-raw')).forEach((button) => {
    button.onclick = async () => {
      const card = button.closest('.thumb-item');
      const target = $('.review-target', card).value;
      const name = $('.review-name', card).value.trim();
      button.disabled = true;
      try {
        await api(taskUrl('/raw/classify'), {
          method: 'POST',
          json: { file: button.dataset.classifyReview, kind: target, name },
        });
        toast(`已归类为${target === 'main' ? '主图' : target === 'detail' ? '详情图' : 'SKU 图'}`, 'success');
        await refreshTask();
      } catch (error) {
        button.disabled = false;
        toast(error.message, 'error');
      }
    };
  });
  $('#openRawFolder').onclick = async () => {
    try {
      await api(taskUrl('/open-folder'), { method: 'POST' });
    } catch (error) {
      toast(error.message, 'error');
    }
  };
  $('#uploadBtn').onclick = async () => {
    const input = $('#uploadFiles');
    if (!input.files || !input.files.length) {
      toast('请先选择文件', 'error');
      return;
    }
    const form = new FormData();
    form.append('kind', $('#uploadKind').value);
    Array.from(input.files).forEach((file) => form.append('files', file));
    try {
      const response = await fetch(taskUrl('/upload'), { method: 'POST', body: form });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || '上传失败');
      toast(`已上传 ${data.data.saved} 个文件`, 'success');
      await refreshTask();
    } catch (error) {
      toast(error.message, 'error');
    }
  };
}

async function loadSuggestions() {
  if (state.slotOptions) return;
  const data = await api(taskUrl('/suggestions'));
  state.suggestions = data;
  state.slotOptions = {};
  (data.slots || []).forEach((slot) => {
    const outputs = state.meta.outputs || {};
    const records = [outputs.main_pc?.[slot.slot], outputs.main_mobile?.[slot.slot]];
    const source = records.filter(Boolean)
      .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''))
      .map((record) => record.source).find((file) =>
      Object.values(state.raw).some((files) => files.includes(file)));
    state.slotOptions[slot.slot] = { ...slot, source: source || slot.source, bullets: slot.bullets || [] };
  });
  state.global = {
    accent: (data.slots[0] || {}).accent || '#E8467C',
    bg: (data.slots[0] || {}).bg || '#F7F4F0',
    text_color: (data.slots[0] || {}).text_color || '#1A1A1A',
  };
  if (!state.detailSelection.size) {
    const available = detailSources();
    const detailRecords = asRecordList(state.meta.outputs?.detail);
    const previous = detailRecords
      .map((record) => record?.source).filter((source) => available.includes(source));
    const lastMode = detailRecords.find((record) => typeof record?.autoOrdered === 'boolean')?.autoOrdered;
    if (lastMode !== undefined) state.detailAutoOrder = lastMode;
    state.detailSelection = new Set(previous.length ? previous : available);
  }
}

function sourceOptions(selected, includeEmpty = false) {
  const groups = [
    ['主图', state.raw.main || []],
    ['详情图', state.raw.detail || []],
    ['SKU 图', state.raw.sku || []],
  ];
  let html = includeEmpty ? '<option value="">— 请选择 —</option>' : '';
  groups.forEach(([label, files]) => {
    if (!files || !files.length) return;
    html += `<optgroup label="${label}">${files.map((file) => {
      const name = file.split('/').pop();
      return `<option value="${esc(file)}" ${file === selected ? 'selected' : ''}>${esc(name)}</option>`;
    }).join('')}</optgroup>`;
  });
  return html;
}

function templateOptions(selected) {
  const list = (state.templates && state.templates.main) || [];
  return list.map((item) => `<option value="${esc(item.id)}" ${item.id === selected ? 'selected' : ''}>${esc(item.name)}</option>`).join('');
}

function previewHtml(records, label) {
  if (!records) return '';
  const list = Array.isArray(records) ? records : [records];
  return list.filter((record) => record && record.file).map((record) => `
    <div class="preview-item">
      <a href="javascript:void(0)" data-preview="${esc(record.file)}">
        <img src="${currentMedia(record.file, 240)}" alt="">
      </a>
      <button type="button" class="btn btn-sm btn-secondary edit-image-btn" data-edit="${esc(record.file)}">编辑</button>
      <div class="preview-label">${esc(label)} · ${record.width}×${record.height} · ${fmtBytes(record.bytes)}</div>
      ${(record.issues || []).length ? `<div class="issues">${esc(record.issues.join('；'))}</div>` : ''}
    </div>`).join('');
}

function isInfoIssue(issue) {
  return /已.*放大|已.*压缩|已处理|提示/.test(String(issue || ''));
}

function compactPreviewHtml(records, label, limit = 6) {
  const list = (Array.isArray(records) ? records : [records]).filter((record) => record && record.file);
  if (!list.length) return '<div class="alert alert-info">还没有生成，点击上方按钮即可自动出图。</div>';
  return `
    <div class="mini-gallery">
      ${list.slice(0, limit).map((record) => `
        <button type="button" class="mini-gallery-item" data-preview="${esc(record.file)}" title="${esc(record.file.split('/').pop())}">
          <img src="${currentMedia(record.file, 180)}" alt="">
          <span>${esc(typeof label === 'function' ? label(record) : label)}</span>
        </button>`).join('')}
    </div>
    <div class="small muted mt-8">共 ${list.length} 张${list.length > limit ? `，已显示前 ${limit} 张` : ''}，点击图片可放大查看。</div>`;
}

function renderPreviewHtml(data) {
  const container = $('#colorPreview');
  if (!container) return;
  if (!data || !data.items || !data.items.length) {
    container.innerHTML = '<div class="alert alert-info">暂无预览，请先采集素材。</div>';
    return;
  }
  container.innerHTML = data.items.map((item) => `
    <div class="thumb-item">
      <img src="${currentMedia(item.file, 320)}&v=${Date.now()}" alt="" data-preview="${esc(item.file)}">
      <div class="thumb-name">${esc(item.name)}</div>
    </div>`).join('');
  $$('[data-preview]', container).forEach((image) => {
    image.onclick = () => openLightbox(image.dataset.preview);
  });
}

async function refreshColorPreview() {
  const container = $('#colorPreview');
  if (!container) return;
  const sourceInput = $('.source-picker[data-change="preview"] .source-input');
  const source = sourceInput ? sourceInput.value : '';
  if (!source) {
    container.innerHTML = '<div class="alert alert-info">没有可用素材，无法生成配色预览。</div>';
    return;
  }
  const slot = state.slotOptions && state.slotOptions[1] ? state.slotOptions[1] : {};
  const key = JSON.stringify([
    source, state.global.accent, state.global.bg, state.global.text_color,
    slot.headline, slot.subhead, slot.badge, (slot.bullets || []).join(','),
  ]);
  if (state.previewKey === key && state.previewData) {
    renderPreviewHtml(state.previewData);
    return;
  }
  container.innerHTML = '<div class="small muted">正在生成配色缩约图...</div>';
  try {
    const data = await api(taskUrl('/preview/colors'), {
      method: 'POST',
      json: {
        source,
        accent: state.global.accent,
        bg: state.global.bg,
        text_color: state.global.text_color,
        headline: slot.headline || '高腰显瘦',
        subhead: slot.subhead || '舒适百搭',
        bullets: slot.bullets || ['高弹不勒', '亲肤面料'],
        badge: slot.badge || '',
        footer: slot.footer || '',
      },
    });
    state.previewKey = key;
    state.previewData = data;
    renderPreviewHtml(data);
  } catch (error) {
    container.innerHTML = `<div class="alert alert-error">${esc(error.message)}</div>`;
  }
}

function scheduleColorPreview() {
  clearTimeout(state.previewTimer);
  state.previewTimer = setTimeout(refreshColorPreview, 250);
}

function scheduleSlotGenerate(slot) {
  clearTimeout(state['slotTimer' + slot]);
  const taskId = state.currentId;
  state['slotTimer' + slot] = setTimeout(() => {
    if (state.currentId === taskId) generateOne(Number(slot), { silent: true });
  }, 450);
}

function scheduleWhiteGenerate() {
  clearTimeout(state.whiteTimer);
  state.whiteTimer = setTimeout(generateWhite, 450);
}

function initSourcePickers() {
  $$('.source-picker').forEach((root) => {
    if (root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    const input = $('.source-input', root);
    const button = $('.source-current', root);
    const panel = $('.source-panel', root);
    if (!input || !button || !panel) return;

    const renderButton = () => {
      const rel = input.value;
      if (!rel) {
        button.innerHTML = '<span class="muted">未选择素材</span>';
        return;
      }
      button.innerHTML = `
        <img src="${currentMedia(rel, 96)}" alt="">
        <span>${esc(rel.split('/').pop())}</span>
        <span class="muted small">更换</span>`;
    };

    const renderPanel = () => {
      const groups = [['main', '主图'], ['detail', '详情图'], ['sku', 'SKU 图']];
      let html = '';
      groups.forEach(([kind, label]) => {
        const files = state.raw[kind] || [];
        if (!files.length) return;
        html += `
          <div class="source-group">
            <div class="small muted">${label} (${files.length})</div>
            <div class="source-grid">
              ${files.map((rel) => `
                <button type="button" class="source-item ${rel === input.value ? 'selected' : ''}" data-source="${esc(rel)}" title="${esc(rel)}">
                  <img src="${currentMedia(rel, 120)}" alt="">
                  <span>${esc(rel.split('/').pop())}</span>
                </button>`).join('')}
            </div>
          </div>`;
      });
      panel.innerHTML = html || '<div class="small muted">暂无可用素材</div>';
      $$('[data-source]', panel).forEach((item) => {
        item.onclick = () => {
          input.value = item.dataset.source;
          renderButton();
          panel.classList.add('hidden');
          const change = root.dataset.change || '';
          if (change === 'preview') {
            scheduleColorPreview();
          } else if (change.startsWith('slot:')) {
            const slot = change.split(':')[1];
            if (state.slotOptions && state.slotOptions[slot]) state.slotOptions[slot].source = input.value;
            scheduleSlotGenerate(slot);
          } else if (change === 'white') {
            scheduleWhiteGenerate();
          }
        };
      });
    };

    button.onclick = () => {
      if (panel.classList.contains('hidden')) {
        renderPanel();
        panel.classList.remove('hidden');
      } else {
        panel.classList.add('hidden');
      }
    };
    renderButton();
  });
}

function applyColorPreset(preset) {
  if (!preset) return;
  state.selectedPreset = preset.id;
  state.global.accent = preset.accent;
  state.global.bg = preset.bg;
  state.global.text_color = preset.text;
  Object.values(state.slotOptions || {}).forEach((option) => {
    option.accent = preset.accent;
    option.bg = preset.bg;
    option.text_color = preset.text;
  });
  if ($('#globalAccent')) $('#globalAccent').value = preset.accent;
  if ($('#globalBg')) $('#globalBg').value = preset.bg;
  if ($('#globalText')) $('#globalText').value = preset.text;
  $$('[data-preset]', $('#panel-create')).forEach((button) => {
    button.classList.toggle('active', button.dataset.preset === preset.id);
  });
  scheduleColorPreview();
}

async function openTaskFolder(subpath) {
  if (!state.autoOpenFolder) return;
  try {
    await api(taskUrl('/open-folder'), { method: 'POST', json: { subpath } });
  } catch (error) {
    toast('打开文件夹失败：' + error.message, 'error');
  }
}

async function renderCreate() {
  await loadSuggestions();
  const outputMeta = state.meta.outputs || {};
  const rawSources = [
    ...(state.raw.main || []),
    ...(state.raw.detail || []),
    ...(state.raw.sku || []),
  ];
  const outputRecords = [
    ...asRecordList(outputMeta.main_pc),
    ...asRecordList(outputMeta.main_mobile),
    ...asRecordList(outputMeta.detail),
    ...asRecordList(outputMeta.sku),
    ...asRecordList(outputMeta.white),
  ].filter((record) => record && record.file);
  const issueRecords = outputRecords.filter((record) => (record.issues || []).length);
  const actionIssueRecords = issueRecords.filter((record) => (record.issues || []).some((issue) => !isInfoIssue(issue)));
  const infoIssueRecords = issueRecords.filter((record) => (record.issues || []).every((issue) => isInfoIssue(issue)));
  const skuRecords = asRecordList(outputMeta.sku).filter((record) => record && record.file);
  const whiteRecords = asRecordList(outputMeta.white).filter((record) => record && record.file);
  const hasSkuSources = (state.raw.sku || []).length > 0;
  const hasWhiteSources = (state.raw.sku || []).length + (state.raw.main || []).length + (state.raw.detail || []).length > 0;
  const completedSlots = [1, 2, 3, 4, 5].filter((slot) => (
    (outputMeta.main_pc || {})[String(slot)] || (outputMeta.main_mobile || {})[String(slot)]
  )).length;
  const templateHelp = ((state.templates && state.templates.main) || [])
    .map((item) => `<div class="small muted">${esc(item.id)}：${esc(item.desc || '')}</div>`).join('');
  const slotCards = [1, 2, 3, 4, 5].map((slot) => {
    const option = state.slotOptions[slot] || {};
    const variants = option.variants || [];
    const zoom = Math.round(Number(option.photo_zoom ?? 1) * 100);
    const offsetX = Math.round(Number(option.photo_x ?? 0));
    const offsetY = Math.round(Number(option.photo_y ?? 0));
    return `
      <div class="card slot-card">
        <div class="slot-head">
          <div><span class="slot-number">${slot}</span><strong>${esc(option.role || '主图')}</strong></div>
          <button class="btn btn-primary btn-sm" data-gen-slot="${slot}" ${rawSources.length ? '' : 'disabled'}>按设置生成</button>
        </div>
        <div class="slot-fields">
          <div class="slot-source-row">
            <button type="button" class="slot-source-button" data-replace-slot="${slot}" title="${esc(option.source || '点击选择主图')}">
              ${option.source
                ? `<img src="${currentMedia(option.source, 360)}" alt="当前素材">`
                : '<span class="slot-source-empty">选择主图</span>'}
              <span class="slot-source-action">更换主图</span>
            </button>
            <input type="hidden" class="source-input" data-slot="${slot}" data-field="source" value="${esc(option.source)}">
            <div class="slot-source-side">
              <label class="field"><span>模板</span><select data-slot="${slot}" data-field="template">${templateOptions(option.template)}</select></label>
              <label class="field"><span>画面模式</span>
                <select data-slot="${slot}" data-field="photo_mode">
                  ${['cover', 'contain', 'whiten'].map((mode) => `<option value="${mode}" ${option.photo_mode === mode ? 'selected' : ''}>${mode === 'cover' ? '铺满裁切' : mode === 'contain' ? '完整显示' : '浅底提亮'}</option>`).join('')}
                </select>
              </label>
            </div>
          </div>
          <div class="slot-photo-controls">
            <div class="slot-photo-head">
              <strong>产品构图</strong>
              <button type="button" class="btn btn-sm" data-photo-reset="${slot}">重置</button>
            </div>
            <div class="grid grid-3">
              <label class="field"><span>缩放 <b data-photo-label="zoom:${slot}">${zoom}%</b></span><input type="range" data-slot="${slot}" data-field="photo_zoom" min="50" max="250" step="5" value="${zoom}"></label>
              <label class="field"><span>左右 <b data-photo-label="x:${slot}">${offsetX}</b></span><input type="range" data-slot="${slot}" data-field="photo_x" min="-100" max="100" step="5" value="${offsetX}"></label>
              <label class="field"><span>上下 <b data-photo-label="y:${slot}">${offsetY}</b></span><input type="range" data-slot="${slot}" data-field="photo_y" min="-100" max="100" step="5" value="${offsetY}"></label>
            </div>
            <div class="small muted">拖动滑块即可移动 / 放大缩小产品，松开后自动重新出图。</div>
          </div>
          <details class="slot-more"><summary>文案与出图规格（可展开）</summary>
            <label class="field"><span>主标题</span><input data-slot="${slot}" data-field="headline" value="${esc(option.headline)}"></label>
            <div class="grid grid-2">
              <label class="field"><span>副标题</span><input data-slot="${slot}" data-field="subhead" value="${esc(option.subhead)}"></label>
              <label class="field"><span>角标（如“7色可选”）</span><input data-slot="${slot}" data-field="badge" value="${esc(option.badge)}"></label>
            </div>
            <label class="field"><span>卖点（用逗号、顿号或空格分隔）</span><input data-slot="${slot}" data-field="bullets" value="${esc((option.bullets || []).join('，'))}"></label>
            <label class="field"><span>底部文案</span><input data-slot="${slot}" data-field="footer" value="${esc(option.footer)}"></label>
            <div class="row">
              <label class="checkbox"><input type="checkbox" data-slot="${slot}" data-field="variants_pc" ${variants.includes('pc') ? 'checked' : ''}> 电脑端 1:1</label>
              <label class="checkbox"><input type="checkbox" data-slot="${slot}" data-field="variants_mobile" ${variants.includes('mobile') ? 'checked' : ''}> 手机端 3:4</label>
              <label class="checkbox"><input type="checkbox" data-slot="${slot}" data-field="show_text" ${option.show_text !== false ? 'checked' : ''}> 显示文案</label>
            </div>
          </details>
        </div>
      </div>`;
  }).join('');
  const detailFiles = detailSources();
  const detailOrdered = Array.from(state.detailSelection);
  const detailChecks = detailFiles.map((rel) => {
    const selected = state.detailSelection.has(rel);
    const order = selected ? detailOrdered.indexOf(rel) + 1 : '—';
    return `
      <div class="detail-order-item ${selected ? 'selected' : ''}" data-detail-item="${esc(rel)}">
        <label class="detail-order-check" title="选用 / 取消">
          <input type="checkbox" class="detail-pick" data-rel="${esc(rel)}" ${selected ? 'checked' : ''}>
        </label>
        <button type="button" class="detail-order-thumb" data-preview="${esc(rel)}" title="预览">
          <img src="${currentMedia(rel, 120)}" alt="">
        </button>
        <span class="detail-order-badge">${order}</span>
        <div class="detail-order-name" title="${esc(rel)}">${esc(rel.split('/').pop())}</div>
        <div class="detail-order-actions">
          <button type="button" class="btn btn-sm" data-detail-move="up" data-rel="${esc(rel)}" title="上移">↑</button>
          <button type="button" class="btn btn-sm" data-detail-move="down" data-rel="${esc(rel)}" title="下移">↓</button>
        </div>
      </div>`;
  }).join('');
  const mainOutputs = outputMeta.main_pc || {};
  const mobileOutputs = outputMeta.main_mobile || {};
  const editedRecords = asRecordList(outputMeta.edited).filter((record) => record && record.file);
  const detailOutputRecords = asRecordList(outputMeta.detail).filter((record) => record && record.file);
  const designCards = [1, 2, 3, 4, 5].map((slot) => {
    const option = state.slotOptions[slot] || {};
    const pc = mainOutputs[String(slot)];
    const mobile = mobileOutputs[String(slot)];
    const selectedVariant = state.slotPreviewVariants[slot] || (pc || !mobile ? 'pc' : 'mobile');
    const record = selectedVariant === 'mobile' ? mobile : pc;
    const role = (state.suggestions && state.suggestions.slots && state.suggestions.slots[slot - 1] || {}).role || '主图';
    return `
      <div class="design-card">
        <div class="design-compare">
          <div class="design-compare-cell">
            <span class="compare-label">原始素材</span>
            ${option.source
              ? `<button type="button" class="design-compare-image" data-preview="${esc(option.source)}"><img src="${currentMedia(option.source, 260)}" alt="原始素材"></button>`
              : '<div class="design-compare-empty">先选择素材</div>'}
          </div>
          <div class="design-compare-cell">
            <div class="compare-label-row">
              <span class="compare-label">成品预览</span>
              <div class="variant-toggle">
                <button type="button" class="${selectedVariant === 'pc' ? 'active' : ''}" aria-pressed="${selectedVariant === 'pc'}" data-slot-preview="${slot}" data-variant="pc">电脑端</button>
                <button type="button" class="${selectedVariant === 'mobile' ? 'active' : ''}" aria-pressed="${selectedVariant === 'mobile'}" data-slot-preview="${slot}" data-variant="mobile">手机端</button>
              </div>
            </div>
            <button type="button" class="design-compare-image" data-slot-output-open="${slot}" data-preview="${esc(record ? record.file : '')}" ${record ? '' : 'disabled'}>
              ${record ? `<img data-slot-output-image="${slot}" src="${currentMedia(record.file, 260)}" alt="成品预览">` : '<span class="compare-empty">尚未生成</span>'}
            </button>
            <div class="compare-meta" data-slot-output-meta="${slot}">
              ${esc(slotOutputInfo(record, selectedVariant, option.source))}
            </div>
          </div>
        </div>
        <div class="design-info">
          <strong>${slot}. ${esc(role)}</strong>
          <div class="slot-quality" data-slot-quality="${slot}">
            ${record && (record.issues || []).length
              ? `<div class="issues">${esc(record.issues.join('；'))}</div>`
              : record
                ? '<span class="quality-ok">当前规格检查通过</span>'
                : '<span class="small muted">生成后会自动检查尺寸与文件大小</span>'}
          </div>
        </div>
        <div class="design-actions">
          <button type="button" class="btn btn-primary btn-sm" data-slot-edit="${slot}" data-variant="${selectedVariant}" ${record ? '' : 'disabled'}>打开主图编辑</button>
          <button type="button" class="btn btn-sm" data-replace-slot="${slot}">更换主图</button>
          <button type="button" class="btn btn-sm" data-render-variant="${slot}" data-variant="${selectedVariant}" ${option.source ? '' : 'disabled'}>${slotOutputAction(record, selectedVariant)}</button>
        </div>
      </div>`;
  }).join('');
  const workflowGuide = `
    <div class="workflow-guide">
      <button type="button" class="workflow-step" data-workflow-step="assets">
        <span class="workflow-index">01</span><span><strong>准备素材</strong><small>${rawSources.length ? `可用图片 ${rawSources.length} 张` : '还没有可用图片'}</small></span><b>查看素材 →</b>
      </button>
      <button type="button" class="workflow-step" data-workflow-step="design">
        <span class="workflow-index">02</span><span><strong>设计主图</strong><small>${completedSlots}/5 个卡位已有成品</small></span><b>去设计 →</b>
      </button>
      <button type="button" class="workflow-step" data-workflow-step="review">
        <span class="workflow-index">03</span><span><strong>检查并导出</strong><small>${actionIssueRecords.length ? `${actionIssueRecords.length} 张需要处理` : outputRecords.length ? (infoIssueRecords.length ? '规格通过，含生成提示' : '当前检查项均通过') : '生成后自动检查规格'}</small></span><b>查看检查 →</b>
      </button>
    </div>
    ${rawSources.length ? '' : `
      <div class="alert alert-info">
        先导入或上传商品图片，再开始设计。进入“原始素材”页可以导入文件夹、网页文件或手动上传。
        <button type="button" class="btn btn-sm" data-goto="raw">去准备素材</button>
      </div>`}`;
  const designBoard = `
    <div class="card" data-workflow-anchor="design">
      <div class="card-head">
        <h3>5 张主图设计台 <span class="sub">对照原图检查效果；可单张重做或编辑成品</span></h3>
        <div class="row">
          <button class="btn btn-sm" id="viewAllBtn">查看全部成品</button>
          <button class="btn btn-primary btn-sm" id="genAllBtn" data-view-after="main" ${rawSources.length ? '' : 'disabled'}>生成 5 张主图</button>
        </div>
      </div>
      <div class="card-body compare-hint">每张卡片都可对照原始素材与成品；选择 PC / 手机预览后，可单独重做、换主图、编辑成品或进入画布编辑。</div>
      <div class="card-body"><div class="design-grid">${designCards}</div></div>
    </div>`;
  const detailBusy = state.detailBusy.has(state.currentId);
  const detailSpecs = state.settings?.specs?.detail || {};
  const detailWarnings = detailOutputRecords.filter((record) => record.issues?.length).length;
  const detailWorkbench = `
    <div class="card" data-workflow-anchor="detail">
      <div class="card-head">
        <h3>详情页工作台</h3>
        <div class="row">
          <button class="btn btn-sm" id="previewDetailBtn" ${detailOutputRecords.length ? '' : 'disabled'}>查看详情成品</button>
          <button class="btn btn-primary btn-sm" id="genDetailBtn" disabled>${detailBusy ? '美化中…' : '一键美化'}</button>
        </div>
      </div>
      <div class="card-body">
        <div class="detail-workbench">
          <div class="detail-picker">
            <div class="row detail-source-bar">
              <strong>${state.raw.detail?.length ? '详情素材' : '可用主图素材'}</strong>
              <span class="small muted" id="detailSelectedCount"></span>
              <button type="button" class="btn btn-sm" id="detailSelectAll">全选</button>
              <button type="button" class="btn btn-sm" id="detailClearSelection">取消全选</button>
              <button type="button" class="btn btn-sm" data-goto="raw">管理素材</button>
            </div>
            <div class="detail-order-grid">${detailChecks || '<p class="small muted">上传详情图或主图素材后即可美化。</p>'}</div>
          </div>
          <div class="detail-settings">
            <label class="checkbox"><input type="checkbox" id="detailAutoOrder" ${state.detailAutoOrder ? 'checked' : ''}> 自动排序</label>
            <p class="small muted">按素材名称识别全貌、卖点、场景、细节、规格和说明。无明确线索的素材保持相对顺序。</p>
            <strong>成品</strong>
            <p class="small muted">等比缩放、提亮暗部、增强清晰度，优先在画面变化较小的位置分段。</p>
            <div class="small muted">宽 ${esc(detailSpecs.width ?? 750)} px · 单段最多 ${esc(Math.min(detailSpecs.segment_height || 1500, detailSpecs.max_height || 2000))} px${detailSpecs.max_bytes ? ` · 每段上限 ${fmtBytes(detailSpecs.max_bytes)}` : ''}</div>
            ${detailOutputRecords.length
              ? `<p class="small" role="status">已生成 ${detailOutputRecords.length} 段${detailWarnings ? ` · ${detailWarnings} 段有质量提示` : ''}</p>`
              : '<p class="small muted">美化完成后可预览整页。</p>'}
          </div>
        </div>
      </div>
    </div>`;
  const skuWhiteCard = `
    <div class="card sku-white-card">
      <div class="card-head">
        <h3>SKU 图与白底图 <span class="sub">按淘宝规范自动出图，主图和详情之外的两类常用图</span></h3>
        <span class="small muted">SKU ${skuRecords.length} 张 · 白底 ${whiteRecords.length} 张</span>
      </div>
      <div class="card-body">
        <div class="grid grid-2 subtool-grid">
          <section class="subtool">
            <div class="subtool-head">
              <div>
                <strong>SKU 图</strong>
                <p>800×800 · 自动提亮 · 可显示颜色名</p>
              </div>
              <button class="btn btn-primary btn-sm" id="genSkuBtn" data-view-after="sku" ${hasSkuSources ? '' : 'disabled'}>${skuRecords.length ? '重新生成 SKU 图' : '生成 SKU 图'}</button>
            </div>
            <div class="row subtool-options">
              <label class="checkbox"><input type="checkbox" id="skuWhiten" checked> 浅色背景提亮</label>
              <label class="checkbox"><input type="checkbox" id="skuName" checked> 显示颜色名</label>
              <label class="field inline-field"><span>底色</span><input type="color" id="skuBg" value="#FFFFFF"></label>
            </div>
            ${hasSkuSources ? '' : '<div class="small muted">还没有 SKU 素材，先到“素材”页采集或上传 SKU 图。</div>'}
            ${compactPreviewHtml(skuRecords, 'SKU 图')}
          </section>
          <section class="subtool">
            <div class="subtool-head">
              <div>
                <strong>白底图</strong>
                <p>电脑端 800×800 · 手机端 750×1000</p>
              </div>
              <button class="btn btn-primary btn-sm" id="genWhiteBtn" data-view-after="white" ${hasWhiteSources ? '' : 'disabled'}>${whiteRecords.length ? '重新生成白底图' : '生成白底图'}</button>
            </div>
            <div class="subtool-options">
              <div class="field source-picker" data-change="white" style="position:relative">
                <span>主体来源（建议选 SKU 白底图）</span>
                <input type="hidden" class="source-input" id="whiteSource" value="${esc((state.raw.sku || [])[0] || (state.raw.main || [])[0] || '')}">
                <button type="button" class="source-current"></button>
                <div class="source-panel hidden"></div>
              </div>
              <label class="checkbox"><input type="checkbox" id="whiteWhiten" checked> 提亮浅色背景</label>
            </div>
            ${hasWhiteSources ? '' : '<div class="small muted">还没有可用素材，先到“素材”页采集或上传图片。</div>'}
            ${compactPreviewHtml(whiteRecords, (record) => (String(record.file).includes('mobile') ? '白底手机' : '白底 PC'))}
          </section>
        </div>
      </div>
    </div>`;
  const editedCard = `
    <div class="card">
      <div class="card-head">
        <h3>编辑成品 <span class="sub">手动改过的图片统一归档，不会覆盖未编辑的成品</span></h3>
        <div class="row">
          <span class="small muted">${editedRecords.length} 张</span>
          <button class="btn btn-sm" id="viewEditedBtn" ${editedRecords.length ? '' : 'disabled'}>查看编辑图</button>
          <button class="btn btn-sm" id="openEditedFolder" ${editedRecords.length ? '' : 'disabled'}>打开文件夹</button>
        </div>
      </div>
      <div class="card-body">
        ${editedRecords.length
          ? `${compactPreviewHtml(editedRecords, '编辑图', 8)}
             <div class="small muted mt-8">“保存覆盖”会同步更新对应成品；“另存为新图”只在这里留档。</div>`
          : '<div class="alert alert-info">还没有编辑成品。只有进入图片编辑器手动改图后，这里才会出现记录；未编辑的成品不受影响。</div>'}
      </div>
    </div>`;
  const qualityStatus = actionIssueRecords.length
    ? `${actionIssueRecords.length} 个需处理`
    : infoIssueRecords.length
      ? `${infoIssueRecords.length} 条提示`
      : outputRecords.length
        ? '规格通过'
        : '尚无成品';
  const qualityPanel = `
    <div class="card quality-panel" data-workflow-anchor="review">
      <div class="card-head">
        <h3>出图检查</h3>
        <span class="sub">${outputRecords.length} 个成品 · ${qualityStatus}</span>
      </div>
      <div class="card-body">
        <div class="quality-checks">
          <span>尺寸规格</span><span>文件体积</span><span>详情分段</span><span>白底四角</span>
        </div>
        ${actionIssueRecords.length
          ? `<div class="alert alert-warn"><strong>有 ${actionIssueRecords.length} 个成品需要处理。</strong>请回到上方对应卡位，点击“更新电脑端 / 更新手机端”或“按设置生成”，系统会按当前规格重新生成并压缩文件。</div>
             <ul class="quality-issue-list">${actionIssueRecords.slice(0, 8).map((record) => `<li><strong>${esc(record.file.split('/').pop())}</strong>：${esc(record.issues.join('；'))}</li>`).join('')}</ul>`
          : infoIssueRecords.length
            ? `<div class="alert alert-info"><strong>基础规格全部通过。</strong>下面 ${infoIssueRecords.length} 条是生成时的自动处理提示，不需要额外操作，可以直接导出。</div>
               <ul class="quality-info-list">${infoIssueRecords.slice(0, 8).map((record) => `<li><strong>${esc(record.file.split('/').pop())}</strong>：${esc(record.issues.join('；'))}</li>`).join('')}</ul>`
            : outputRecords.length
              ? '<div class="quality-ok quality-ok-block">已生成图片全部通过当前尺寸、体积等基础检查。上架前仍建议人工核对商品信息和平台规则。</div>'
              : '<div class="small muted">生成主图、SKU 图或详情页后，这里会自动汇总检查结果。</div>'}
        <div class="row mt-12">
          <button type="button" class="btn btn-sm" data-workflow-step="design">返回检查卡位</button>
          <button type="button" class="btn btn-primary btn-sm" data-goto="export" ${outputRecords.length ? '' : 'disabled'}>检查完成，去导出</button>
        </div>
      </div>
    </div>`;
  const advancedHtml = `
    <div class="adv-tabs">
      <button type="button" class="adv-tab active" data-adv-tab="style">风格配色</button>
      <button type="button" class="adv-tab" data-adv-tab="main">主图文案</button>
    </div>
    <div class="adv-section active" data-adv="style">
    <div class="card">
      <div class="card-head">
        <h3>全局设置 <span class="sub">配色应用到全部主图</span></h3>
      </div>
      <div class="card-body">
        <div class="grid grid-3">
          <label class="field"><span>主题色</span><input type="color" id="globalAccent" value="${esc(state.global.accent)}"></label>
          <label class="field"><span>背景色</span><input type="color" id="globalBg" value="${esc(state.global.bg)}"></label>
          <label class="field"><span>文字色</span><input type="color" id="globalText" value="${esc(state.global.text_color)}"></label>
        </div>
        <div class="grid grid-2">
          <div class="field source-picker" data-change="preview" style="position:relative">
            <span>预览来源（点开可看原图并切换）</span>
            <input type="hidden" class="source-input" value="${esc((state.raw.main || [])[0] || (state.raw.detail || [])[0] || (state.raw.sku || [])[0] || '')}">
            <button type="button" class="source-current"></button>
            <div class="source-panel hidden"></div>
          </div>
          <div style="padding-top:22px">
            <label class="checkbox"><input type="checkbox" id="autoOpenFolder" ${state.autoOpenFolder ? 'checked' : ''}> 生成 / 导出后自动打开文件夹</label>
            <div class="small muted mt-8">选配色方案或改颜色后，预览图会自动刷新；正式出图使用同一套渲染逻辑。</div>
          </div>
        </div>
        <div class="field">
          <span>配色方案（点击自动应用）</span>
          <div class="row" id="colorPresets">
            ${state.colorPresets.map((preset) => `
              <button type="button" class="preset-btn ${state.selectedPreset === preset.id ? 'active' : ''}" data-preset="${esc(preset.id)}">
                <span class="preset-dot" style="background:${esc(preset.accent)}"></span>${esc(preset.name)}
              </button>`).join('')}
          </div>
        </div>
        <div id="colorPreview" class="thumb-grid mt-8"></div>
        <div class="small muted mt-8">模板说明：${templateHelp}</div>
      </div>
    </div>
    </div>
    <div class="adv-section" data-adv="main">
    ${slotCards}
    </div>`;
  $('#panel-create').innerHTML = `${workflowGuide}${designBoard}${detailWorkbench}${skuWhiteCard}${qualityPanel}${editedCard}
    <details class="card advanced-panel">
      <summary>高级：配色与主图文案（一般不用改）</summary>
      <div class="card-body">${advancedHtml}</div>
    </details>`;

  $$('[data-slot]', $('#panel-create')).forEach((element) => {
    const handler = (event) => {
      const slot = element.dataset.slot;
      const field = element.dataset.field;
      const option = state.slotOptions[slot];
      if (!option) return;
      if (field === 'bullets') {
        option.bullets = element.value.split(/[,，、\s]+/).map((item) => item.trim()).filter(Boolean);
      } else if (field === 'variants_pc' || field === 'variants_mobile') {
        const variants = new Set(option.variants || []);
        if (field === 'variants_pc') element.checked ? variants.add('pc') : variants.delete('pc');
        else element.checked ? variants.add('mobile') : variants.delete('mobile');
        option.variants = Array.from(variants);
      } else if (field === 'show_text') {
        option.show_text = element.checked;
      } else if (field === 'photo_zoom' || field === 'photo_x' || field === 'photo_y') {
        option[field] = Number(element.value);
        const labelKey = { photo_zoom: 'zoom', photo_x: 'x', photo_y: 'y' }[field];
        const label = $(`[data-photo-label="${labelKey}:${slot}"]`);
        if (label) label.textContent = element.value;
        if (event && event.type === 'change') scheduleSlotGenerate(slot);
      } else {
        option[field] = element.value;
      }
    };
    element.addEventListener('input', handler);
    element.addEventListener('change', handler);
  });
  $$('[data-photo-reset]', $('#panel-create')).forEach((button) => {
    button.onclick = () => {
      const slot = button.dataset.photoReset;
      const option = state.slotOptions[slot];
      if (!option) return;
      option.photo_zoom = 1;
      option.photo_x = 0;
      option.photo_y = 0;
      $$(`[data-slot="${slot}"]`, $('#panel-create')).forEach((element) => {
        if (['photo_zoom', 'photo_x', 'photo_y'].includes(element.dataset.field)) element.value = String(option[element.dataset.field]);
        $$('[data-photo-label]', $('#panel-create')).forEach((label) => {
          const parts = (label.dataset.photoLabel || '').split(':');
          if (parts[1] !== String(slot)) return;
          const key = parts[0];
          const optionKey = key === 'zoom' ? 'photo_zoom' : key === 'x' ? 'photo_x' : 'photo_y';
          label.textContent = String(option[optionKey] ?? 0);
        });
      });
      scheduleSlotGenerate(slot);
    };
  });
  $$('[data-replace-slot]', $('#panel-create')).forEach((button) => {
    button.onclick = () => {
      const slot = button.dataset.replaceSlot;
      const taskId = state.currentId;
      const current = state.slotOptions[slot]?.source || '';
      openSourcePicker({
        title: `更换第 ${slot} 张主图`,
        current,
        onSelect: async (rel) => {
          await requestMainSlot(Number(slot), ['pc', 'mobile'], rel);
          if (state.currentId !== taskId) return;
          await refreshTask();
          toast(`第 ${slot} 张主图的电脑端和手机端均已更新`, 'success');
        },
      });
    };
  });
  $$('[data-gen-slot]', $('#panel-create')).forEach((button) => {
    button.onclick = () => generateOne(Number(button.dataset.genSlot), { button });
  });
  $$('[data-render-variant]', $('#panel-create')).forEach((button) => {
    button.onclick = () => generateOne(Number(button.dataset.renderVariant), {
      variants: [button.dataset.variant], button,
    });
  });
  $$('[data-slot-preview]', $('#panel-create')).forEach((button) => {
    button.onclick = () => setSlotPreview(
      parseInt(button.dataset.slotPreview, 10),
      button.dataset.variant,
    );
  });
  $$('[data-workflow-step]', $('#panel-create')).forEach((button) => {
    button.onclick = () => {
      const step = button.dataset.workflowStep;
      if (step === 'assets') {
        switchTab('raw');
        return;
      }
      const target = step === 'review'
        ? $('[data-workflow-anchor="review"]')
        : $('[data-workflow-anchor="design"]');
      target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };
  });
  $$('[data-goto]', $('#panel-create')).forEach((button) => {
    button.onclick = () => switchTab(button.dataset.goto);
  });
  $$('[data-preview]', $('#panel-create')).forEach((link) => {
    link.onclick = () => {
      if (link.dataset.preview) openLightbox(link.dataset.preview);
    };
  });
  $$('[data-edit]', $('#panel-create')).forEach((button) => {
    button.onclick = () => openImageEditor(button.dataset.edit);
  });
  $$('[data-slot-edit]', $('#panel-create')).forEach((button) => {
    button.onclick = () => {
      const kind = button.dataset.variant === 'mobile' ? 'main_mobile' : 'main_pc';
      location.assign(`/studio/${encodeURIComponent(state.currentId)}/${kind}/${button.dataset.slotEdit}`);
    };
  });
  $$('[data-edit-raw]', $('#panel-create')).forEach((button) => {
    button.onclick = () => openImageEditor(button.dataset.editRaw, { fromRaw: true });
  });
  $$('.detail-pick', $('#panel-create')).forEach((checkbox) => {
    checkbox.onchange = () => {
      if (checkbox.checked) state.detailSelection.add(checkbox.dataset.rel);
      else state.detailSelection.delete(checkbox.dataset.rel);
      const item = checkbox.closest('.detail-order-item');
      if (item) item.classList.toggle('selected', checkbox.checked);
      refreshDetailOrderUi();
    };
  });
  $$('.detail-order-thumb', $('#panel-create')).forEach((button) => {
    button.onclick = () => openLightbox(button.dataset.preview);
  });
  $$('[data-detail-move]', $('#panel-create')).forEach((button) => {
    button.onclick = () => moveDetail(button.dataset.rel, button.dataset.detailMove === 'down' ? 1 : -1);
  });
  $('#detailSelectAll').onclick = () => {
    state.detailSelection = new Set(detailSources());
    refreshDetailOrderUi();
  };
  $('#detailClearSelection').onclick = () => {
    state.detailSelection = new Set();
    refreshDetailOrderUi();
  };
  $('#detailAutoOrder').onchange = (event) => { state.detailAutoOrder = event.target.checked; };
  ['Accent', 'Bg', 'Text'].forEach((key) => {
    const element = $('#global' + key);
    element.oninput = () => {
      const field = key === 'Accent' ? 'accent' : key === 'Bg' ? 'bg' : 'text_color';
      state.global[field] = element.value;
      Object.values(state.slotOptions).forEach((option) => { option[field] = element.value; });
      state.selectedPreset = '';
      $$('[data-preset]', $('#panel-create')).forEach((button) => button.classList.remove('active'));
      scheduleColorPreview();
    };
    element.onchange = () => scheduleColorPreview();
  });
  $$('[data-preset]', $('#panel-create')).forEach((button) => {
    button.onclick = () => {
      const preset = state.colorPresets.find((item) => item.id === button.dataset.preset);
      applyColorPreset(preset);
    };
  });
  $$('[data-adv-tab]', $('#panel-create')).forEach((button) => {
    button.onclick = () => {
      $$('[data-adv-tab]', $('#panel-create')).forEach((item) => item.classList.toggle('active', item === button));
      $$('.adv-section', $('#panel-create')).forEach((section) => {
        section.classList.toggle('active', section.dataset.adv === button.dataset.advTab);
      });
    };
  });
  $('#viewAllBtn').onclick = () => viewOutputs('main');
  $('#viewEditedBtn').onclick = () => viewOutputs('edited');
  $('#openEditedFolder').onclick = async () => {
    try {
      await api(taskUrl('/open-folder'), { method: 'POST', json: { subpath: 'output/edited' } });
    } catch (error) {
      toast(error.message, 'error');
    }
  };
  $('#previewDetailBtn').onclick = () => openDetailPreview();
  initSourcePickers();
  $('#autoOpenFolder').onchange = () => { state.autoOpenFolder = $('#autoOpenFolder').checked; };
  $('#genAllBtn').onclick = generateAll;
  $('#genDetailBtn').onclick = generateDetail;
  refreshDetailOrderUi();
  $('#genSkuBtn').onclick = generateSku;
  $('#genWhiteBtn').onclick = generateWhite;
  refreshColorPreview();
}

function refreshDetailOrderUi() {
  const grid = $('.detail-order-grid', $('#panel-create'));
  if (!grid) return;
  const available = new Set(detailSources());
  const busy = state.detailBusy.has(state.currentId);
  const selectedSources = [...state.detailSelection].filter((rel) => available.has(rel));
  const indexes = new Map(selectedSources.map((rel, index) => [rel, index]));
  const items = $$('.detail-order-item', grid);
  items.forEach((item) => {
    const rel = item.dataset.detailItem;
    const index = indexes.get(rel);
    const selected = index !== undefined;
    const order = selected ? index + 1 : '—';
    item.classList.toggle('selected', selected);
    const checkbox = $('.detail-pick', item);
    if (checkbox) {
      checkbox.checked = selected;
      checkbox.disabled = busy;
    }
    const badge = $('.detail-order-badge', item);
    if (badge) badge.textContent = order;
    $('[data-detail-move="up"]', item).disabled = busy || !selected || index === 0;
    $('[data-detail-move="down"]', item).disabled = busy || !selected || index === selectedSources.length - 1;
  });
  items.sort((a, b) => (indexes.get(a.dataset.detailItem) ?? Infinity) - (indexes.get(b.dataset.detailItem) ?? Infinity));
  items.forEach((item) => grid.append(item));
  $('#detailSelectedCount').textContent = `已选 ${selectedSources.length} / ${available.size} 张`;
  const button = $('#genDetailBtn');
  for (const id of ['detailAutoOrder', 'detailSelectAll', 'detailClearSelection']) $('#'+id).disabled = busy;
  $('#detailAutoOrder').checked = state.detailAutoOrder;
  button.disabled = busy || !selectedSources.length;
  button.textContent = busy ? '美化中…' : '一键美化';
}

function detailSources() {
  return state.raw.detail?.length ? state.raw.detail : state.raw.main || [];
}

function moveDetail(rel, delta) {
  const list = Array.from(state.detailSelection);
  const index = list.indexOf(rel);
  if (index < 0) return;
  const target = index + delta;
  if (target < 0 || target >= list.length) return;
  const item = list.splice(index, 1)[0];
  list.splice(target, 0, item);
  state.detailSelection = new Set(list);
  state.detailAutoOrder = false;
  refreshDetailOrderUi();
}

function openDetailPreview() {
  const records = asRecordList(state.meta.outputs?.detail).filter((record) => record && record.file);
  if (!records.length) {
    toast('请先点击「一键美化」', 'error');
    return;
  }
  openModal({
    title: `详情页长图 · 共 ${records.length} 张`,
    className: 'wide',
    body: `
    ${records.some((record) => record.issues?.length)
      ? `<details class="detail-preview-notes"><summary>质量提示</summary><ul>${records.flatMap((record, index) =>
        (record.issues || []).map((issue) => `<li>第 ${index + 1} 段 · ${esc(issue)}</li>`)).join('')}</ul></details>`
      : ''}
    <div class="detail-preview-stack">
      ${records.map((record) => `
        <div class="detail-preview-item">
          <img src="${currentMedia(record.file)}" width="${esc(record.width || 750)}" height="${esc(record.height || 0)}" loading="lazy" alt="${esc(record.sourceRole || '详情素材')} · 第 ${esc(record.segment || 1)} 段">
        </div>`).join('')}
    </div>`,
    foot: '<button class="btn" id="detailPreviewClose">关闭预览</button>',
    onMount: () => {
      $('#detailPreviewClose').onclick = closeModal;
    },
  });
}

function slotPayload(slot, variantsOverride) {
  const option = { ...(state.slotOptions[slot] || {}) };
  option.slot = slot;
  if (variantsOverride && variantsOverride.length) option.variants = variantsOverride;
  option.accent = state.global.accent;
  option.bg = state.global.bg;
  option.text_color = state.global.text_color;
  return option;
}

function requestMainSlot(slot, variants, source) {
  clearTimeout(state['slotTimer' + slot]);
  const taskId = state.currentId;
  const option = state.slotOptions[slot];
  const path = taskUrl('/generate/main');
  const key = `${taskId}/${slot}`;
  const payload = slotPayload(slot, variants);
  const previous = state.slotRequests.get(key) || Promise.resolve();
  const pending = previous.catch(() => {}).then(async () => {
    payload.source = source ?? option?.source ?? payload.source;
    const records = await api(path, { method: 'POST', json: payload });
    if (source !== undefined && state.currentId === taskId && state.slotOptions?.[slot] === option && option) {
      option.source = source;
    }
    return records;
  });
  state.slotRequests.set(key, pending);
  return pending.finally(() => {
    if (state.slotRequests.get(key) === pending) state.slotRequests.delete(key);
  });
}

function slotOutputAction(record, variant) {
  return `${record ? '更新' : '生成'}${variant === 'mobile' ? '手机端' : '电脑端'}`;
}

function slotOutputInfo(record, variant, source) {
  const label = variant === 'mobile' ? '手机端' : '电脑端';
  if (!record) return `${label}尚未生成`;
  const details = `${label} · ${record.width}×${record.height} · ${fmtBytes(record.bytes)}`;
  return record.source && source && record.source !== source ? `${details} · 使用旧素材，待更新` : details;
}

function setSlotPreview(slot, variant) {
  const activeRecord = (variant === 'mobile'
    ? state.meta.outputs?.main_mobile
    : state.meta.outputs?.main_pc)?.[String(slot)];
  state.slotPreviewVariants[slot] = variant;
  const openButton = $(`[data-slot-output-open="${slot}"]`);
  const editButton = $(`[data-slot-edit="${slot}"]`);
  const meta = $(`[data-slot-output-meta="${slot}"]`);
  const quality = $(`[data-slot-quality="${slot}"]`);
  const renderButton = $(`[data-render-variant="${slot}"]`);
  if (renderButton) {
    renderButton.dataset.variant = variant;
    renderButton.textContent = slotOutputAction(activeRecord, variant);
  }
  if (meta) meta.textContent = slotOutputInfo(activeRecord, variant, state.slotOptions[slot]?.source);
  if (editButton) {
    editButton.dataset.variant = variant;
    editButton.disabled = !activeRecord;
  }
  if (openButton && activeRecord) {
    openButton.innerHTML = `<img data-slot-output-image="${slot}" src="${currentMedia(activeRecord.file, 260)}" alt="成品预览">`;
    openButton.disabled = false;
    openButton.dataset.preview = activeRecord.file;
    if (quality) {
      quality.innerHTML = (activeRecord.issues || []).length
        ? `<div class="issues">${esc(activeRecord.issues.join('；'))}</div>`
        : '<span class="quality-ok">当前规格检查通过</span>';
    }
  } else if (openButton) {
    openButton.innerHTML = '<span class="compare-empty">尚未生成</span>';
    openButton.disabled = true;
    openButton.dataset.preview = '';
    if (quality) quality.innerHTML = '<span class="small muted">生成后会自动检查尺寸与文件大小</span>';
  }
  $$(`[data-slot-preview="${slot}"]`).forEach((button) => {
    const active = button.dataset.variant === variant;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

async function generateOne(slot, options = {}) {
  const taskId = state.currentId;
  const { button } = options;
  if (button?.disabled) return;
  const label = button?.textContent;
  try {
    if (button) {
      button.disabled = true;
      button.innerHTML = '<span class="spinner"></span> 生成中';
    }
    const records = await requestMainSlot(slot, options.variants);
    if (state.currentId !== taskId) return;
    await refreshTask();
    if (!options.silent) {
      const targets = Object.keys(records).map((variant) => variant === 'mobile' ? '手机端' : '电脑端');
      toast(`第 ${slot} 张主图${targets.join('和')}已更新`, 'success');
    }
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = label;
    }
  }
}

async function generateAll(options = {}) {
  const silent = options.silent === true;
  try {
    const button = $('#genAllBtn');
    if (button) {
      button.disabled = true;
      button.innerHTML = '<span class="spinner"></span> 生成中';
    }
    const slots = [1, 2, 3, 4, 5].map(slotPayload);
    const result = await api(taskUrl('/generate/main/all'), { method: 'POST', json: { slots } });
    if (!silent) {
      if (result.errors && result.errors.length) {
        toast(`部分卡位失败：${result.errors.map((item) => item.slot + '#' + item.error).join('；')}`, 'error');
      } else {
        toast('5 张主图已生成（PC + 手机）', 'success');
      }
      await openTaskFolder('output');
    }
    await refreshTask();
    if (!silent) viewOutputs('main');
  } catch (error) {
    if (!silent) toast(error.message, 'error');
    await refreshTask();
  }
}

async function generateDetail() {
  const taskId = state.currentId;
  if (state.detailBusy.has(taskId)) return;
  const available = new Set(detailSources());
  const sources = [...state.detailSelection].filter((source) => available.has(source));
  if (!sources.length) {
    toast('请先选择至少一张详情原图', 'error');
    return;
  }
  state.detailBusy.add(taskId);
  refreshDetailOrderUi();
  try {
    const records = await api(taskUrl('/generate/detail'), {
      method: 'POST', json: { sources, beautify: true, auto_order: state.detailAutoOrder },
    });
    if (state.currentId !== taskId) return;
    state.detailSelection = new Set(records.map((record) => record.source));
    await refreshTask();
    if (state.currentId === taskId && state.activeTab === 'create') openDetailPreview();
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    state.detailBusy.delete(taskId);
    if (state.currentId === taskId) refreshDetailOrderUi();
  }
}

async function generateSku() {
  try {
    const button = $('#genSkuBtn');
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> 生成中';
    await api(taskUrl('/generate/sku'), {
      method: 'POST',
      json: {
        whiten: $('#skuWhiten').checked,
        show_name: $('#skuName').checked,
        bg: $('#skuBg').value,
        accent: state.global.accent,
      },
    });
    toast('SKU 图已生成', 'success');
    await refreshTask();
    viewOutputs('sku');
  } catch (error) {
    toast(error.message, 'error');
    await refreshTask();
  }
}

async function generateWhite() {
  try {
    const button = $('#genWhiteBtn');
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> 生成中';
    await api(taskUrl('/generate/white'), {
      method: 'POST',
      json: { source: $('#whiteSource').value, whiten: $('#whiteWhiten').checked, variants: ['pc', 'mobile'] },
    });
    toast('白底图已生成', 'success');
    await refreshTask();
    viewOutputs('white');
  } catch (error) {
    toast(error.message, 'error');
    await refreshTask();
  }
}

function initKeywordDraft() {
  if (state.keywordDraft) return;
  const kw = state.meta.keywords || {};
  state.keywordDraft = {
    text: (kw.competitorTitles || []).join('\n'),
    productTitle: kw.productTitle || state.meta.title || '',
    titleFacts: kw.titleFacts || '',
    imageTags: JSON.parse(JSON.stringify(kw.imageTags || {})),
    titles: JSON.parse(JSON.stringify(kw.titles || [])),
    selectedTitle: kw.selectedTitle || '',
  };
  if (!state.analysis && kw.analyzedAt) {
    state.analysis = {
      categories: kw.categories || {},
      imageTags: kw.imageTags || {},
      colorTags: kw.colorTags || {},
      bannedFound: kw.bannedFound || [],
      brandFound: kw.brandFound || [],
      stats: kw.stats || {},
    };
    if (!state.selectedWords.size) {
      Object.values(kw.categories || {}).forEach((category) => {
        (category.words || []).slice(0, 2).forEach((entry) => state.selectedWords.add(entry.word));
      });
    }
  }
}

async function renderKeywords() {
  initKeywordDraft();
  const draft = state.keywordDraft;
  $('#panel-keywords').innerHTML = `
    <div class="card">
      <div class="card-head">
        <h3>竞品标题 <span class="sub">每行一条，可粘贴 10–50 条</span></h3>
        <button class="btn btn-primary btn-sm" id="analyzeBtn">生成 5 组新品标题</button>
      </div>
      <div class="card-body">
        <label class="field"><span>自定义商品标题</span><input id="kwProductTitle" maxlength="300" value="${esc(draft.productTitle)}"></label>
        <label class="field"><span>已确认的商品属性（选填，用逗号分隔）</span><input id="kwTitleFacts" maxlength="800" value="${esc(draft.titleFacts)}" placeholder="例如 高腰直筒版型，侧边口袋，日常通勤"></label>
        <textarea id="kwText" rows="6" placeholder="竞品标题一行一条，例如：高腰显瘦瑜伽裤女夏季薄款外穿打底裤">${esc(draft.text)}</textarea>
        <div class="small muted mt-8">竞品标题用于参考关键词频次。推荐标题使用自定义标题和已确认属性，优先凑足 30 字。</div>
      </div>
    </div>
    <div id="kwResults"></div>
    <div class="card">
      <div class="card-head"><h3>主图画面标签 <span class="sub">用于“结合主图出词”，可手动修改</span></h3></div>
      <div class="card-body">
        <div class="grid grid-3" id="kwImageTags">
          ${[1, 2, 3, 4, 5].map((slot) => `
            <label class="field"><span>第 ${slot} 张 · ${esc((state.suggestions?.slots?.[slot - 1] || {}).role || '')}</span>
              <input data-tag-slot="${slot}" value="${esc((draft.imageTags[String(slot)] || []).join('，'))}">
            </label>`).join('')}
        </div>
        <div class="small muted" id="kwColorTags"></div>
        <button class="btn btn-secondary btn-sm mt-8" id="saveKwBtn">保存关键词与标题</button>
      </div>
    </div>`;
  $('#kwProductTitle').oninput = () => { draft.productTitle = $('#kwProductTitle').value; };
  $('#kwTitleFacts').oninput = () => { draft.titleFacts = $('#kwTitleFacts').value; };
  $('#kwText').oninput = () => { draft.text = $('#kwText').value; };
  $$('[data-tag-slot]').forEach((input) => {
    input.oninput = () => {
      draft.imageTags[input.dataset.tagSlot] = input.value.split(/[,，、\s]+/).map((item) => item.trim()).filter(Boolean);
    };
  });
  const colorTags = state.analysis?.colorTags || (state.meta.keywords || {}).colorTags || {};
  const colorText = Object.entries(colorTags).map(([slot, items]) => {
    const names = (items || []).map((item) => item.name || item).join('、');
    return names ? `第 ${slot} 张主色：${names}` : '';
  }).filter(Boolean).join('；');
  $('#kwColorTags').textContent = colorText || '未识别到主图主色';
  $('#analyzeBtn').onclick = () => analyzeKeywords();
  $('#saveKwBtn').onclick = saveKeywords;
  renderKeywordResults();
}

function renderKeywordResults() {
  const container = $('#kwResults');
  if (!container) return;
  const analysis = state.analysis;
  if (!analysis) {
    container.innerHTML = '<div class="card"><div class="card-body small muted">填写商品标题后即可生成推荐。</div></div>';
    return;
  }
  const categories = analysis.categories || {};
  const categoryHtml = Object.entries(categories).map(([key, category]) => {
    const chips = (category.words || []).map((entry) => {
      const selected = state.selectedWords.has(entry.word) ? 'selected' : '';
      const source = (entry.source || []).join('/');
      return `<button class="chip ${selected}" data-word="${esc(entry.word)}" title="${esc(source)}">${esc(entry.word)}<span class="chip-count">${entry.count}</span></button>`;
    }).join('');
    return `<div class="word-col"><h4>${esc(category.name || key)}</h4><div class="word-body">${chips || '<span class="small muted">暂无</span>'}</div></div>`;
  }).join('');
  const titles = (state.keywordDraft.titles || []).map((item, index) => {
    const checked = state.keywordDraft.selectedTitle === item.title ? 'checked' : '';
    return `
      <div class="title-candidate">
        <input type="radio" name="selectedTitle" data-title-index="${index}" ${checked}>
        <div class="tc-body">
          <input class="title-text" data-title-index="${index}" value="${esc(item.title)}">
          <div class="tc-meta"><span class="title-length">${Array.from(item.title).length} / 30 字</span> · ${esc(item.source || '')}</div>
        </div>
      </div>`;
  }).join('');
  const warnings = [];
  if ((analysis.bannedFound || []).length) warnings.push(`<div class="alert alert-warn">检测到敏感词：${esc(analysis.bannedFound.join('、'))}，请人工确认。</div>`);
  if ((analysis.brandFound || []).length) warnings.push(`<div class="alert alert-warn">疑似品牌词：${esc(analysis.brandFound.join('、'))}，建议从标题中去掉。</div>`);
  container.innerHTML = `
    <div class="card">
      <div class="card-head"><h3>新品标题推荐</h3></div>
      <div class="card-body">${titles || '<div class="small muted">暂无候选标题</div>'}
        ${(state.keywordDraft.titles.length < 5 || state.keywordDraft.titles.some((item) => item.length < 30))
          ? '<p class="small muted">补充真实材质、版型、用途等属性，可生成更多接近 30 字的候选。</p>' : ''}
      </div>
    </div>
    ${warnings.join('')}
    <div class="card">
      <div class="card-head">
        <h3>分类词表 <span class="sub">点击词条可选择，蓝框为已选</span></h3>
        <button class="btn btn-secondary btn-sm" id="genTitlesBtn">优先使用选中的已确认词</button>
      </div>
      <div class="card-body">
        <div class="grid grid-3">${categoryHtml}</div>
        <div class="small muted mt-12">分析标题 ${analysis.stats?.titleCount || 0} 条，候选词 ${analysis.stats?.wordCount || 0} 个</div>
      </div>
    </div>`;
  $$('[data-word]', container).forEach((button) => {
    button.onclick = () => {
      const word = button.dataset.word;
      if (state.selectedWords.has(word)) state.selectedWords.delete(word);
      else state.selectedWords.add(word);
      button.classList.toggle('selected', state.selectedWords.has(word));
    };
  });
  $$('.title-text', container).forEach((input) => {
    input.oninput = () => {
      const index = parseInt(input.dataset.titleIndex, 10);
      const wasSelected = $('input[name="selectedTitle"][data-title-index="' + index + '"]', container).checked;
      state.keywordDraft.titles[index].title = input.value;
      const length = Array.from(input.value).length;
      state.keywordDraft.titles[index].length = length;
      $('.title-length', input.parentElement).textContent = length + ' / 30 字' + (length > 30 ? '（超出）' : '');
      if (wasSelected) {
        state.keywordDraft.selectedTitle = input.value;
      }
    };
  });
  $$('input[name="selectedTitle"]', container).forEach((radio) => {
    radio.onchange = () => {
      const index = parseInt(radio.dataset.titleIndex, 10);
      state.keywordDraft.selectedTitle = state.keywordDraft.titles[index].title;
    };
  });
  $('#genTitlesBtn').onclick = () => analyzeKeywords([...state.selectedWords]);
}

async function analyzeKeywords(words = []) {
  const button = $('#analyzeBtn');
  if (button.disabled) return;
  const draft = state.keywordDraft;
  if (!draft.productTitle.trim()) {
    toast('请填写自定义商品标题', 'error');
    return;
  }
  try {
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> 分析中';
    const analysis = await api(taskUrl('/keywords/analyze'), {
      method: 'POST',
      json: {
        text: $('#kwText').value,
        productTitle: $('#kwProductTitle').value,
        titleFacts: draft.titleFacts,
        newProduct: true,
        words,
        imageTags: state.keywordDraft.imageTags,
      },
    });
    if (state.keywordDraft !== draft) return;
    state.analysis = analysis;
    state.keywordDraft.titles = analysis.titles || [];
    if (!draft.titles.some((item) => item.title === draft.selectedTitle)) draft.selectedTitle = '';
    state.selectedWords = new Set();
    Object.values(analysis.categories || {}).forEach((category) => {
      (category.words || []).slice(0, 2).forEach((entry) => state.selectedWords.add(entry.word));
    });
    Object.entries(analysis.imageTags || {}).forEach(([slot, tags]) => {
      state.keywordDraft.imageTags[slot] = tags || [];
      const input = $(`[data-tag-slot="${slot}"]`);
      if (input) input.value = (tags || []).join('，');
    });
    renderKeywordResults();
    const colorText = Object.entries(analysis.colorTags || {}).map(([slot, items]) => {
      const names = (items || []).map((item) => item.name || item).join('、');
      return names ? `第 ${slot} 张主色：${names}` : '';
    }).filter(Boolean).join('；');
    const colorTags = $('#kwColorTags');
    if (colorTags) colorTags.textContent = colorText || '未识别到主图主色';
    toast('已生成 ' + draft.titles.length + ' 组新品标题', 'success');
  } catch (error) {
    toast(error.message, 'error');
  } finally {
    button.disabled = false;
    button.textContent = '生成 5 组新品标题';
  }
}

async function saveKeywords() {
  try {
    const draft = state.keywordDraft;
    if (draft.titles.some((item) => Array.from(item.title).length > 30)) {
      toast('请将超长标题调整为 30 字以内', 'error');
      return;
    }
    await api(taskUrl('/keywords/save'), {
      method: 'POST', json: { ...draft, competitorTitles: draft.text.split('\n').map((line) => line.trim()).filter(Boolean) },
    });
    toast('关键词与标题已保存', 'success');
    await refreshTask();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function renderExport() {
  if (!state.exportSections) {
    const latest = (state.meta.exports || []).slice(-1)[0];
    state.exportSections = latest?.sections
      ? { ...latest.sections }
      : { main_pc: true, main_mobile: true, white: true, detail: true, sku: true, edited: true, video: true, keywords: true, meta: true };
  }
  const labels = {
    main_pc: '电脑端主图', main_mobile: '手机端主图', white: '白底图', detail: '详情页图',
    sku: 'SKU 图', edited: '编辑成品', video: '视频', keywords: '关键词表', meta: '商品与素材信息',
  };
  const outputs = state.outputs || {};
  const fileRows = Object.entries(outputs).map(([kind, files]) => {
    const list = files || [];
    return `<div class="stat-pill">${esc(labels[kind] || kind)}<strong>${list.length}</strong></div>`;
  }).join('');
  const exports = (state.meta.exports || []).slice(-5).reverse().map((item) => `
    <tr><td>${esc(fmtDate(item.createdAt))}</td><td>${esc(item.downloadName)}</td><td>${fmtBytes(item.bytes)}</td><td>${item.fileCount}</td>
      <td><a href="${taskUrl('/export/download')}">下载</a></td></tr>`).join('');
  $('#panel-export').innerHTML = `
    <div class="card">
      <div class="card-head"><h3>导出上架素材包</h3><button class="btn btn-primary btn-sm" id="exportBtn">打包导出</button></div>
      <div class="card-body">
        <div class="grid grid-4">
          ${Object.keys(labels).map((key) => `
            <label class="checkbox"><input type="checkbox" data-section="${key}" ${state.exportSections[key] ? 'checked' : ''}> ${labels[key]}</label>`).join('')}
        </div>
        <div class="stat-pills mt-16">${fileRows}</div>
        <div class="small muted mt-12">zip 内使用 ASCII 目录名并附中文说明，避免 Windows 解压乱码；CSV 为 UTF-8 BOM，Excel 可直接打开。</div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>导出历史</h3></div>
      <div class="card-body" style="padding:0;overflow-x:auto">
        ${exports ? `<table><thead><tr><th>时间</th><th>文件</th><th>大小</th><th>文件数</th><th>操作</th></tr></thead><tbody>${exports}</tbody></table>` : '<div class="card-body small muted">暂无导出记录</div>'}
      </div>
    </div>`;
  $$('[data-section]', $('#panel-export')).forEach((checkbox) => {
    checkbox.onchange = () => { state.exportSections[checkbox.dataset.section] = checkbox.checked; };
  });
  $('#exportBtn').onclick = async () => {
    try {
      const button = $('#exportBtn');
      button.disabled = true;
      button.innerHTML = '<span class="spinner"></span> 打包中';
      const result = await api(taskUrl('/export'), { method: 'POST', json: { sections: state.exportSections } });
      toast(`导出完成：${fmtBytes(result.bytes)}`, 'success');
      await openTaskFolder('output/export');
      await refreshTask();
    } catch (error) {
      toast(error.message, 'error');
      await refreshTask();
    }
  };
}

function newTaskModal() {
  const folderExample = 'D:\\taobao\\1688_1041092037687';
  openModal({
    title: '新建任务',
    className: 'wide',
    body: `
      <div class="modal-tabs">
        <button data-section="url" class="active">链接直采</button>
        <button data-section="folder">导入文件夹</button>
        <button data-section="pages">导入网页文件</button>
        <button data-section="zip">导入压缩包</button>
        <button data-section="manual">手动新建</button>
        <button data-section="demo">示例商品</button>
      </div>
      <div class="modal-section active" data-section="url">
        <label class="field"><span>1688 商品链接</span><input id="ntUrl" placeholder="https://detail.1688.com/offer/1041092037687.html"></label>
        <label class="field"><span>任务标题（可选）</span><input id="ntUrlTitle" placeholder="留空则使用商品 ID"></label>
        <details>
          <summary class="small muted" style="cursor:pointer">高级：浏览器 Cookie（直采失败时再填）</summary>
          <textarea id="ntCookie" class="mt-8" rows="3" placeholder="F12 → 网络 → 任意请求 → 复制 Cookie 请求头"></textarea>
          <div class="small muted mt-8">Cookie 只保存在本机，不写日志。1688 风控严格时直采可能失败，建议改用其他导入方式。</div>
        </details>
        <button class="btn btn-primary mt-12" id="ntUrlBtn">创建并开始采集</button>
      </div>
      <div class="modal-section" data-section="folder">
        <label class="field"><span>本机素材文件夹路径</span><input id="ntFolder" value="${esc(folderExample)}"></label>
        <div class="alert alert-info small">按目录名识别：主图/main、详情/detail、sku/规格、视频/video；若存在 info.json 会读取标题与 SKU 名称。</div>
        <button class="btn btn-primary" id="ntFolderBtn">导入文件夹</button>
      </div>
      <div class="modal-section" data-section="pages">
        <label class="field"><span>浏览器保存的网页或接口文件</span><input type="file" id="ntPages" multiple accept=".html,.json,.txt"></label>
        <div class="alert alert-info small">支持 components.json、desc.html、完整商品页 HTML。可在浏览器保存网页，或从 F12 网络面板保存接口响应。</div>
        <button class="btn btn-primary" id="ntPagesBtn">导入文件</button>
      </div>
      <div class="modal-section" data-section="zip">
        <label class="field"><span>素材压缩包</span><input type="file" id="ntZip" accept=".zip"></label>
        <button class="btn btn-primary" id="ntZipBtn">导入压缩包</button>
      </div>
      <div class="modal-section" data-section="manual">
        <label class="field"><span>任务标题</span><input id="ntManualTitle" placeholder="例如：夏季新款瑜伽裤"></label>
        <label class="field"><span>商品 ID（可选）</span><input id="ntManualId"></label>
        <div class="alert alert-info small">创建后可在“原始素材”里按类型上传图片。</div>
        <button class="btn btn-primary" id="ntManualBtn">创建空白任务</button>
      </div>
      <div class="modal-section" data-section="demo">
        <div class="alert alert-info">示例商品位于 D:\\taobao\\1688_1041092037687，含主图、详情图与 SKU 图，可快速验证出图与关键词流程。</div>
        <button class="btn btn-primary" id="ntDemoBtn">导入示例商品</button>
      </div>`,
    onMount: (root) => {
      $$('.modal-tabs button', root).forEach((button) => {
        button.onclick = () => {
          $$('.modal-tabs button', root).forEach((item) => item.classList.remove('active'));
          $$('.modal-section', root).forEach((section) => section.classList.remove('active'));
          button.classList.add('active');
          $(`.modal-section[data-section="${button.dataset.section}"]`, root).classList.add('active');
        };
      });
      const afterCreate = async (data) => {
        closeModal();
        await loadTasks();
        await selectTask(data.id);
      };
      const run = async (button, action) => {
        try {
          button.disabled = true;
          button.innerHTML = '<span class="spinner"></span> 处理中';
          const data = await action();
          await afterCreate(data);
          toast('任务已创建', 'success');
        } catch (error) {
          toast(error.message, 'error');
          button.disabled = false;
          button.textContent = button.dataset.originalText || '重试';
        }
      };
      const mark = (id) => {
        const button = $(id);
        button.dataset.originalText = button.textContent;
        return button;
      };
      $('#ntUrlBtn').onclick = () => mark('#ntUrlBtn') && run($('#ntUrlBtn'), () => api('/api/tasks', {
        method: 'POST',
        json: { mode: 'url', url: $('#ntUrl').value, title: $('#ntUrlTitle').value, cookie: $('#ntCookie').value },
      }));
      $('#ntFolderBtn').onclick = () => mark('#ntFolderBtn') && run($('#ntFolderBtn'), () => api('/api/tasks', {
        method: 'POST', json: { mode: 'folder', folder: $('#ntFolder').value },
      }));
      $('#ntManualBtn').onclick = () => mark('#ntManualBtn') && run($('#ntManualBtn'), () => api('/api/tasks', {
        method: 'POST', json: { mode: 'manual', title: $('#ntManualTitle').value, offerId: $('#ntManualId').value },
      }));
      $('#ntDemoBtn').onclick = () => mark('#ntDemoBtn') && run($('#ntDemoBtn'), () => api('/api/tasks/demo', { method: 'POST', json: {} }));
      $('#ntPagesBtn').onclick = () => {
        const input = $('#ntPages');
        if (!input.files || !input.files.length) { toast('请选择文件', 'error'); return; }
        const button = mark('#ntPagesBtn');
        run(button, async () => {
          const form = new FormData();
          Array.from(input.files).forEach((file) => form.append('files', file));
          const response = await fetch('/api/tasks/import-pages', { method: 'POST', body: form });
          const data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.error || '导入失败');
          return data.data;
        });
      };
      $('#ntZipBtn').onclick = () => {
        const input = $('#ntZip');
        if (!input.files || !input.files.length) { toast('请选择 zip 文件', 'error'); return; }
        const button = mark('#ntZipBtn');
        run(button, async () => {
          const form = new FormData();
          form.append('file', input.files[0]);
          const response = await fetch('/api/tasks/import-zip', { method: 'POST', body: form });
          const data = await response.json();
          if (!response.ok || !data.ok) throw new Error(data.error || '导入失败');
          return data.data;
        });
      };
    },
  });
}

async function settingsModal() {
  try {
    const settings = await api('/api/settings');
    const download = settings.download || {};
    const aiSettings = settings.ai || {};
    const specs = settings.specs || {};
    const specFields = (key, fields) => `
      <div class="card-body">
        <h4>${esc(key)}</h4>
        <div class="grid grid-2">
          ${fields.map((field) => `<label class="field"><span>${esc(field.label)}</span><input type="number" data-spec="${esc(key)}" data-field="${esc(field.key)}" value="${esc(specs[key]?.[field.key] ?? '')}"></label>`).join('')}
        </div>
      </div>`;
    openModal({
      title: '设置',
      className: 'wide',
      body: `
        <div class="card">
          <div class="card-head"><h3>1688 直采 Cookie</h3></div>
          <div class="card-body">
            <label class="field"><span>Cookie（留空并勾选“保持不变”则不修改）</span>
              <textarea id="setCookie" rows="3" placeholder="${download.cookie === '__SET__' ? '已设置，留空保持不变' : '粘贴浏览器 Cookie'}"></textarea>
            </label>
            <label class="checkbox"><input type="checkbox" id="setCookieClear"> 清空已保存的 Cookie</label>
          </div>
        </div>
        <div class="card">
          <div class="card-head"><h3>淘宝规格参数</h3><span class="sub">修改后对后续生成生效</span></div>
          ${specFields('main_pc', [{ key: 'width', label: 'PC 主图宽' }, { key: 'height', label: 'PC 主图高' }, { key: 'target_bytes', label: '目标体积(B)' }, { key: 'max_bytes', label: '最大体积(B)' }])}
          ${specFields('main_mobile', [{ key: 'width', label: '手机主图宽' }, { key: 'height', label: '手机主图高' }, { key: 'target_bytes', label: '目标体积(B)' }, { key: 'max_bytes', label: '最大体积(B)' }])}
          ${specFields('detail', [{ key: 'width', label: '详情宽' }, { key: 'segment_height', label: '分段高度' }, { key: 'max_height', label: '单张最大高度' }, { key: 'max_bytes', label: '最大体积(B)' }])}
          ${specFields('sku', [{ key: 'width', label: 'SKU 宽' }, { key: 'height', label: 'SKU 高' }, { key: 'max_bytes', label: '最大体积(B)' }])}
        </div>
        <div class="card">
          <div class="card-head"><h3>AI 服务（本地优先）</h3><span class="sub">模型不可用时基础制图仍可使用</span></div>
          <div class="card-body">
            <label class="checkbox"><input type="checkbox" id="setAiEnabled" ${aiSettings.enabled ? 'checked' : ''}> 启用 AI 辅助</label>
            <div class="grid grid-2">
              <label class="field"><span>服务类型</span><select id="setAiProvider"><option value="ollama" ${aiSettings.provider === 'ollama' ? 'selected' : ''}>Ollama 本地模型</option><option value="openai-compatible" ${aiSettings.provider === 'openai-compatible' ? 'selected' : ''}>OpenAI 兼容接口</option></select></label>
              <label class="field"><span>Ollama 地址</span><input id="setOllamaUrl" value="${esc(aiSettings.ollama_url || 'http://127.0.0.1:11434')}"></label>
              <label class="field"><span>文本模型</span><input id="setTextModel" value="${esc(aiSettings.text_model || '')}"></label>
              <label class="field"><span>视觉模型</span><input id="setVisionModel" value="${esc(aiSettings.vision_model || '')}"></label>
            </div>
            <div id="aiStatusHint" class="small muted">正在检查模型状态…</div>
          </div>
        </div>
        <div class="alert alert-info">服务监听：${esc(settings.server?.host || '127.0.0.1')}:${esc(settings.server?.port || 8765)}（改端口需修改 config/settings.json 后重启）。</div>`,
      foot: '<button class="btn" id="setCancel">取消</button><button class="btn btn-primary" id="setSave">保存设置</button>',
      onMount: (root) => {
        $('#setCancel', root).onclick = closeModal;
        $('#setSave', root).onclick = async () => {
          const payload = { specs: {} };
          payload.ai = {
            enabled: $('#setAiEnabled', root).checked,
            provider: $('#setAiProvider', root).value,
            ollama_url: $('#setOllamaUrl', root).value.trim(),
            text_model: $('#setTextModel', root).value.trim(),
            vision_model: $('#setVisionModel', root).value.trim(),
          };
          $$('[data-spec]', root).forEach((input) => {
            const key = input.dataset.spec;
            payload.specs[key] = payload.specs[key] || {};
            payload.specs[key][input.dataset.field] = parseInt(input.value, 10);
          });
          if ($('#setCookieClear', root).checked) {
            payload.download = { cookie: '__CLEAR__' };
          } else if ($('#setCookie', root).value.trim()) {
            payload.download = { cookie: $('#setCookie', root).value };
          } else {
            payload.download = { cookie: '__KEEP__' };
          }
          try {
            await api('/api/settings', { method: 'POST', json: payload });
            state.settings = await api('/api/settings');
            closeModal();
            toast('设置已保存', 'success');
          } catch (error) {
            toast(error.message, 'error');
          }
        };
        api('/api/ai/status').then((result) => {
          const hint = $('#aiStatusHint', root);
          if (hint) hint.textContent = result.message;
        }).catch(() => {});
      },
    });
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function init() {
  $('#newTaskBtn').onclick = newTaskModal;
  $('#emptyNewBtn').onclick = newTaskModal;
  $('#settingsBtn').onclick = settingsModal;
  $('#emptyDemoBtn').onclick = async () => {
    try {
      const data = await api('/api/tasks/demo', { method: 'POST', json: {} });
      await loadTasks();
      await selectTask(data.id);
      toast('示例商品已导入', 'success');
    } catch (error) {
      toast(error.message, 'error');
    }
  };
  $$('.tabs button').forEach((button) => {
    button.onclick = () => switchTab(button.dataset.tab);
  });
  document.addEventListener('click', (event) => {
    $$('.source-panel').forEach((panel) => {
      if (panel.classList.contains('hidden')) return;
      const root = panel.closest('.source-picker');
      const button = root ? $('.source-current', root) : null;
      if (panel.contains(event.target) || (button && button.contains(event.target))) return;
      panel.classList.add('hidden');
    });
  });
  try {
    const [templates, settings] = await Promise.all([api('/api/templates'), api('/api/settings')]);
    state.templates = templates;
    state.settings = settings;
    await loadTasks();
    const params = new URLSearchParams(location.search);
    const taskId = params.get('task');
    if (state.tasks.some((task) => task.id === taskId)) {
      await selectTask(taskId);
      const slot = Number(params.get('slot'));
      const variant = params.get('variant');
      if (slot >= 1 && slot <= 5 && ['pc', 'mobile'].includes(variant)) {
        state.slotPreviewVariants[slot] = variant;
      }
      await switchTab('create');
      if (slot >= 1 && slot <= 5) $('[data-slot-edit="' + slot + '"]')?.closest('.design-card')?.scrollIntoView({ block: 'center' });
    }
  } catch (error) {
    toast(error.message, 'error');
  }
}

init();
