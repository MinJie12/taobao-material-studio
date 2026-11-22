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
  keywordDraft: null,
  analysis: null,
  selectedWords: new Set(),
  rawKind: 'main',
  exportSections: null,
  autoOpenFolder: true,
  previewKey: null,
  previewData: null,
  previewTimer: null,
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
  return mediaUrl(state.currentId, rel, width);
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
            ${counts.main || 0} 主图 / ${counts.detail || 0} 详情
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
  state.suggestions = null;
  state.slotOptions = null;
  state.keywordDraft = null;
  state.analysis = null;
  state.selectedWords = new Set();
  state.detailSelection = new Set();
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
          <div class="stat-pill">PC主图<strong>${out.main_pc || 0}</strong></div>
          <div class="stat-pill">手机主图<strong>${out.main_mobile || 0}</strong></div>
          <div class="stat-pill">详情成品<strong>${out.detail || 0}</strong></div>
          <div class="stat-pill">SKU成品<strong>${out.sku || 0}</strong></div>
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
  renderActivePanel();
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
      <div class="card-head"><h3>操作日志</h3></div>
      <div class="card-body">${logs || '<div class="small muted">暂无日志</div>'}</div>
    </div>`;
  $$('[data-goto]', $('#panel-overview')).forEach((button) => {
    button.onclick = () => switchTab(button.dataset.goto);
  });
  $$('.preview-link', $('#panel-overview')).forEach((link) => {
    link.onclick = () => openLightbox(link.dataset.rel);
  });
}

function openLightbox(rel) {
  openModal({
    title: '素材预览',
    body: `<div style="text-align:center;background:#111;border-radius:8px;padding:12px"><img class="lightbox-img" src="${currentMedia(rel)}" alt=""></div>`,
    lightbox: true,
  });
}

function disposeImageEditor() {
  if (state.editor && state.editor.canvas) {
    try { state.editor.canvas.dispose(); } catch (error) { /* ignore */ }
  }
  state.editor = null;
}

function openImageEditor(rel) {
  disposeImageEditor();
  const name = rel.split('/').pop();
  openModal({
    title: '图片编辑 · ' + name,
    className: 'wide',
    body: `
      <div class="studio-layout">
        <div class="studio-left">
          <div class="editor-group-title">素材库（点击加入画布）</div>
          <div class="studio-library" id="studioLibrary">
            ${[['main', '主图'], ['detail', '详情'], ['sku', 'SKU']].map(([kind, label]) => {
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
            <button type="button" class="btn btn-sm" data-op="stitchH">横向拼接</button>
            <button type="button" class="btn btn-sm" data-op="stitchV">纵向拼接</button>
            <button type="button" class="btn btn-sm" data-op="stitchGrid">九宫格</button>
            <button type="button" class="btn btn-sm" data-op="cutout">一键抠图</button>
            <button type="button" class="btn btn-sm" data-op="rotate">旋转90°</button>
            <button type="button" class="btn btn-sm" data-op="flipx">翻转</button>
            <button type="button" class="btn btn-sm" data-op="undo">撤销</button>
            <button type="button" class="btn btn-sm" data-op="redo">重做</button>
          </div>
          <div class="editor-canvas-wrap"><canvas id="editorCanvas"></canvas></div>
          <div class="row mt-8">
            <label class="field" style="margin:0"><span>文字内容</span><input id="edText" value="输入文字" style="width:200px"></label>
            <label class="field" style="margin:0"><span>颜色</span><input type="color" id="edTextColor" value="#ffffff" style="width:70px"></label>
            <label class="field" style="margin:0"><span>字号</span><input type="number" id="edTextSize" value="48" style="width:80px"></label>
            <label class="checkbox"><input type="checkbox" id="edTextBold" checked> 加粗</label>
            <label class="field" style="margin:0"><span>画笔颜色</span><input type="color" id="edBrushColor" value="#e8467c" style="width:70px"></label>
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
            <div class="small muted">提示：点选画布中的文字或图片即可移动、缩放；右侧可改颜色与层级。</div>
          </div>
          <div id="studioLayers" class="mt-8"></div>
        </div>
      </div>`,
    foot: `
      <button class="btn" id="edCancel">取消</button>
      <button class="btn btn-secondary" id="edSaveAs">另存为新图</button>
      <button class="btn btn-primary" id="edSave">保存覆盖</button>`,
    onMount: (root) => {
      const canvas = new fabric.Canvas('editorCanvas', { backgroundColor: '#ffffff', preserveObjectStacking: true });
      state.editor = { canvas, rel, history: [], index: -1, tool: 'select', cropRect: null, filterTimer: null };
      fabric.Image.fromURL(currentMedia(rel), (image) => {
        canvas.setWidth(image.width || 800);
        canvas.setHeight(image.height || 800);
        image.set({ selectable: true });
        image.sourceFile = rel;
        canvas.add(image);
        canvas.renderAll();
        editorSnapshot();
        editorRefreshProps();
      });
      canvas.on('path:created', () => editorSnapshot());
      canvas.on('selection:created', editorRefreshProps);
      canvas.on('selection:updated', editorRefreshProps);
      canvas.on('selection:cleared', editorRefreshProps);
      canvas.on('object:modified', () => { editorSnapshot(); editorRefreshProps(); });
      $$('[data-add-image]', root).forEach((button) => {
        button.onclick = () => editorAddImage(button.dataset.addImage);
      });
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
      $('#edSave').onclick = () => saveImageEdit(false);
      $('#edSaveAs').onclick = () => saveImageEdit(true);
      $('#edCancel').onclick = () => { disposeImageEditor(); closeModal(); };
      $('.modal-close', root).onclick = () => { disposeImageEditor(); closeModal(); };
      $('.modal-backdrop', root).addEventListener('click', (event) => {
        if (event.target === $('.modal-backdrop', root)) { disposeImageEditor(); closeModal(); }
      });
    },
  });
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
      <div class="row"><button class="btn btn-sm" id="propBold">加粗切换</button><button class="btn btn-sm btn-danger" data-layer="delete">删除</button></div>`;
  } else {
    html = `
      <label class="field"><span>透明度 <b id="propOpacityVal">${Math.round((object.opacity ?? 1) * 100)}</b></span><input type="range" id="propOpacity" min="0" max="100" value="${Math.round((object.opacity ?? 1) * 100)}"></label>
      <label class="field"><span>大小 <b id="propScaleVal">${Math.round((object.scaleX || 1) * 100)}%</b></span><input type="range" id="propScale" min="10" max="300" value="${Math.round((object.scaleX || 1) * 100)}"></label>
      <div class="row">
        <button class="btn btn-sm" data-layer="up">上移一层</button>
        <button class="btn btn-sm" data-layer="down">下移一层</button>
        <button class="btn btn-sm btn-danger" data-layer="delete">删除</button>
      </div>
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
    $('#propCutout').onclick = () => editorCutout();
  }
  $$('[data-layer]', props).forEach((button) => {
    button.onclick = () => {
      const action = button.dataset.layer;
      if (action === 'delete') canvas.remove(object);
      else if (action === 'up') canvas.bringObjectForward(object);
      else if (action === 'down') canvas.sendObjectBackwards(object);
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
  const json = JSON.stringify(editor.canvas.toJSON());
  editor.history = editor.history.slice(0, editor.index + 1);
  editor.history.push(json);
  if (editor.history.length > 30) editor.history.shift();
  editor.index = editor.history.length - 1;
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
  const data = editor.canvas.toDataURL({ format: 'png' });
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
      editor.canvas.clear();
      editor.canvas.setWidth(offscreen.width);
      editor.canvas.setHeight(offscreen.height);
      editor.canvas.add(result);
      editor.canvas.renderAll();
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
    button.disabled = true;
    const dataUrl = editor.canvas.toDataURL({ format: 'png' });
    const result = await api(taskUrl('/image/edit'), {
      method: 'POST',
      json: { file: editor.rel, dataUrl, saveAsNew },
    });
    disposeImageEditor();
    closeModal();
    toast(saveAsNew ? '已另存为新图' : '已保存覆盖原成品图', 'success');
    await refreshTask();
  } catch (error) {
    toast(error.message, 'error');
  }
}

function viewOutputs(kind) {
  const labels = {
    main_pc: '电脑端主图', main_mobile: '手机端主图', detail: '详情页图',
    sku: 'SKU 图', white: '白底图',
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
    ['main', '主图'], ['detail', '详情图'], ['sku', 'SKU 图'], ['video', '视频'],
  ];
  const files = state.raw[state.rawKind] || [];
  const cards = files.map((rel, index) => {
    const name = rel.split('/').pop();
    const isVideo = state.rawKind === 'video';
    const canSelect = state.rawKind === 'detail';
    const checked = state.detailSelection.has(rel) ? 'checked' : '';
    return `
      <div class="thumb-item ${checked ? 'selected' : ''}" data-rel="${esc(rel)}">
        ${canSelect ? `<label class="thumb-check"><input type="checkbox" class="detail-check" data-rel="${esc(rel)}" ${checked}> 选用</label>` : ''}
        ${isVideo
          ? `<div style="height:128px;display:flex;align-items:center;justify-content:center;background:#111;color:#fff;font-size:12px">视频文件</div>`
          : `<img src="${currentMedia(rel, 220)}" alt="" class="raw-thumb">`}
        <div class="thumb-name" title="${esc(rel)}">${index + 1}. ${esc(name)}</div>
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
        ${files.length ? `<div class="thumb-grid">${cards}</div>` : '<div class="alert alert-info">该分类暂无素材。直采失败时可手动上传，或改用导入文件夹。</div>'}
      </div>
    </div>`;
  $$('.kind-btn', $('#panel-raw')).forEach((button) => {
    button.onclick = () => {
      state.rawKind = button.dataset.kind;
      renderRaw();
    };
  });
  $$('.raw-thumb', $('#panel-raw')).forEach((image) => {
    image.onclick = () => openLightbox(image.closest('.thumb-item').dataset.rel);
  });
  $$('.detail-check', $('#panel-raw')).forEach((checkbox) => {
    checkbox.onchange = () => {
      if (checkbox.checked) state.detailSelection.add(checkbox.dataset.rel);
      else state.detailSelection.delete(checkbox.dataset.rel);
      checkbox.closest('.thumb-item').classList.toggle('selected', checkbox.checked);
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
    state.slotOptions[slot.slot] = { ...slot, bullets: slot.bullets || [] };
  });
  state.global = {
    accent: (data.slots[0] || {}).accent || '#E8467C',
    bg: (data.slots[0] || {}).bg || '#F7F4F0',
    text_color: (data.slots[0] || {}).text_color || '#1A1A1A',
  };
  if (!state.detailSelection.size) {
    state.detailSelection = new Set(data.rawGroups?.detail || []);
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
  state['slotTimer' + slot] = setTimeout(() => generateOne(parseInt(slot, 10), { silent: true }), 450);
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
  if (!Object.keys(outputMeta.main_pc || {}).length && state.autoGeneratedFor !== state.currentId) {
    state.autoGeneratedFor = state.currentId;
    const panel = $('#panel-create');
    if (panel) panel.innerHTML = '<div class="card"><div class="card-body">正在自动生成 5 张主图，请稍候…</div></div>';
    await generateAll({ silent: true });
    return;
  }
  const templateHelp = ((state.templates && state.templates.main) || [])
    .map((item) => `<div class="small muted">${esc(item.id)}：${esc(item.desc || '')}</div>`).join('');
  const slotCards = [1, 2, 3, 4, 5].map((slot) => {
    const option = state.slotOptions[slot] || {};
    const pc = (outputMeta.main_pc || {})[String(slot)];
    const mobile = (outputMeta.main_mobile || {})[String(slot)];
    const variants = option.variants || [];
    return `
      <div class="card slot-card">
        <div class="slot-head">
          <div><span class="slot-number">${slot}</span><strong>${esc(option.role || '主图')}</strong></div>
          <button class="btn btn-primary btn-sm" data-gen-slot="${slot}" data-view-after="main">生成并查看</button>
        </div>
        <div class="slot-fields">
          <details class="slot-more"><summary>来源与模板（可展开）</summary>
          <div class="grid grid-3">
            <div class="field source-picker" data-change="slot:${slot}" style="position:relative">
              <span>来源素材（点开看原图）</span>
              <input type="hidden" class="source-input" data-slot="${slot}" data-field="source" value="${esc(option.source)}">
              <button type="button" class="source-current"></button>
              <div class="source-panel hidden"></div>
            </div>
            <label class="field"><span>模板</span><select data-slot="${slot}" data-field="template">${templateOptions(option.template)}</select></label>
            <label class="field"><span>画面模式</span>
              <select data-slot="${slot}" data-field="photo_mode">
                ${['cover', 'contain', 'whiten'].map((mode) => `<option value="${mode}" ${option.photo_mode === mode ? 'selected' : ''}>${mode === 'cover' ? '铺满裁切' : mode === 'contain' ? '完整 containment' : '浅底提亮'}</option>`).join('')}
              </select>
            </label>
          </div>
          </details>
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
        </div>
        <div class="preview-row">
          ${previewHtml(pc, '电脑端')}
          ${previewHtml(mobile, '手机端')}
          ${!pc && !mobile ? '<div class="small muted">尚未生成，点击“生成此张”</div>' : ''}
        </div>
      </div>`;
  }).join('');
  const detailChecks = (state.raw.detail || []).map((rel) => {
    const checked = state.detailSelection.has(rel);
    return `
      <label class="source-item detail-item ${checked ? 'selected' : ''}">
        <input type="checkbox" class="detail-pick" data-rel="${esc(rel)}" ${checked ? 'checked' : ''}>
        <img src="${currentMedia(rel, 120)}" alt="">
        <span>${esc(rel.split('/').pop())}</span>
      </label>`;
  }).join('');
  const mainOutputs = outputMeta.main_pc || {};
  const mobileOutputs = outputMeta.main_mobile || {};
  const designCards = [1, 2, 3, 4, 5].map((slot) => {
    const record = mainOutputs[String(slot)];
    const mobile = mobileOutputs[String(slot)];
    const role = (state.suggestions && state.suggestions.slots && state.suggestions.slots[slot - 1] || {}).role || '主图';
    return `
      <div class="design-card">
        <div class="design-thumb">
          ${record ? `<img src="${currentMedia(record.file, 420)}" alt="">` : '<div class="design-empty">尚未生成</div>'}
        </div>
        <div class="design-info">
          <strong>${slot}. ${esc(role)}</strong>
          <span class="small muted">${record ? `${record.width}×${record.height} · ${fmtBytes(record.bytes)}` : ''}</span>
        </div>
        <div class="design-actions">
          <button type="button" class="btn btn-primary btn-sm" data-design-edit="${esc(record ? record.file : '')}" ${record ? '' : 'disabled'}>打开设计</button>
          ${mobile ? `<button type="button" class="btn btn-sm" data-preview="${esc(mobile.file)}">手机版</button>` : ''}
        </div>
      </div>`;
  }).join('');
  const designBoard = `
    <div class="card">
      <div class="card-head">
        <h3>5 张主图设计台 <span class="sub">点“打开设计”可移动元素、改文字配色、拼接图片与抠图</span></h3>
        <div class="row">
          <button class="btn btn-sm" id="viewAllBtn">查看全部成品</button>
          <button class="btn btn-primary btn-sm" id="genAllBtn" data-view-after="main">生成并查看 5 张</button>
        </div>
      </div>
      <div class="card-body"><div class="design-grid">${designCards}</div></div>
    </div>`;
  const advancedHtml = `
    <div class="adv-tabs">
      <button type="button" class="adv-tab active" data-adv-tab="style">风格配色</button>
      <button type="button" class="adv-tab" data-adv-tab="main">主图文案</button>
      <button type="button" class="adv-tab" data-adv-tab="other">详情 / SKU / 白底</button>
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
    </div>
    <div class="adv-section" data-adv="other">
    <div class="card">
      <div class="card-head"><h3>详情页图</h3><button class="btn btn-primary btn-sm" id="genDetailBtn" data-view-after="detail">生成并查看</button></div>
      <div class="card-body">
        <details class="slot-more"><summary>选择详情原图（默认全选，点开调整）</summary>
          <div class="source-grid" style="max-height:220px;overflow:auto;border:1px solid var(--line-soft);border-radius:8px;padding:10px">${detailChecks || '<span class="small muted">暂无详情原图</span>'}</div>
        </details>
        <div class="grid grid-4 mt-12">
          <label class="field"><span>宽度</span><input id="detailWidth" type="number" value="750"></label>
          <label class="field"><span>分段高度</span><input id="detailSegment" type="number" value="1500"></label>
          <label class="field"><span>详情首屏标题</span><input id="detailCoverTitle" value="${esc(state.meta.title)}"></label>
          <label class="field"><span>首屏副标题</span><input id="detailCoverSub" value=""></label>
        </div>
        <label class="checkbox"><input type="checkbox" id="detailMakeCover" checked> 生成详情首屏</label>
        <div class="preview-row mt-12">${asRecordList(outputMeta.detail).map((record) => previewHtml(record, '详情')).join('')}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>SKU 图</h3><button class="btn btn-primary btn-sm" id="genSkuBtn" data-view-after="sku">生成并查看</button></div>
      <div class="card-body">
        <div class="row">
          <label class="checkbox"><input type="checkbox" id="skuWhiten" checked> 浅色背景提亮</label>
          <label class="checkbox"><input type="checkbox" id="skuName" checked> 显示颜色名</label>
          <label class="field" style="margin:0"><span>底色</span><input type="color" id="skuBg" value="#FFFFFF" style="width:80px"></label>
        </div>
        <div class="preview-row mt-12">${asRecordList(outputMeta.sku).map((record) => previewHtml(record, 'SKU')).join('')}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>白底图</h3><button class="btn btn-primary btn-sm" id="genWhiteBtn" data-view-after="white">生成并查看</button></div>
      <div class="card-body">
        <div class="grid grid-2">
          <div class="field source-picker" data-change="white" style="position:relative">
            <span>主体来源（建议选 SKU 白底图，点开看原图）</span>
            <input type="hidden" class="source-input" id="whiteSource" value="${esc((state.raw.sku || [])[0] || (state.raw.main || [])[0] || '')}">
            <button type="button" class="source-current"></button>
            <div class="source-panel hidden"></div>
          </div>
          <div class="row" style="padding-top:22px">
            <label class="checkbox"><input type="checkbox" id="whiteWhiten" checked> 提亮浅色背景</label>
          </div>
        </div>
        <div class="preview-row mt-12">
          ${previewHtml((outputMeta.white || {}).pc, '白底 PC')}
          ${previewHtml((outputMeta.white || {}).mobile, '白底手机')}
        </div>
      </div>
    </div>
    </div>`;
  $('#panel-create').innerHTML = `${designBoard}
    <details class="card advanced-panel">
      <summary>高级：套版参数、详情图 / SKU 图 / 白底图</summary>
      <div class="card-body">${advancedHtml}</div>
    </details>`;

  $$('[data-slot]', $('#panel-create')).forEach((element) => {
    const handler = () => {
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
      } else {
        option[field] = element.value;
      }
    };
    element.addEventListener('input', handler);
    element.addEventListener('change', handler);
  });
  $$('[data-gen-slot]', $('#panel-create')).forEach((button) => {
    button.onclick = () => generateOne(parseInt(button.dataset.genSlot, 10));
  });
  $$('[data-preview]', $('#panel-create')).forEach((link) => {
    link.onclick = () => openLightbox(link.dataset.preview);
  });
  $$('[data-edit]', $('#panel-create')).forEach((button) => {
    button.onclick = () => openImageEditor(button.dataset.edit);
  });
  $$('[data-design-edit]', $('#panel-create')).forEach((button) => {
    button.onclick = () => {
      if (button.dataset.designEdit) openImageEditor(button.dataset.designEdit);
    };
  });
  $$('.detail-pick', $('#panel-create')).forEach((checkbox) => {
    checkbox.onchange = () => {
      if (checkbox.checked) state.detailSelection.add(checkbox.dataset.rel);
      else state.detailSelection.delete(checkbox.dataset.rel);
      const item = checkbox.closest('.detail-item');
      if (item) item.classList.toggle('selected', checkbox.checked);
    };
  });
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
  initSourcePickers();
  $('#autoOpenFolder').onchange = () => { state.autoOpenFolder = $('#autoOpenFolder').checked; };
  $('#genAllBtn').onclick = generateAll;
  $('#genDetailBtn').onclick = generateDetail;
  $('#genSkuBtn').onclick = generateSku;
  $('#genWhiteBtn').onclick = generateWhite;
  refreshColorPreview();
}

function slotPayload(slot) {
  const option = { ...(state.slotOptions[slot] || {}) };
  option.slot = slot;
  option.accent = state.global.accent;
  option.bg = state.global.bg;
  option.text_color = state.global.text_color;
  return option;
}

async function generateOne(slot, options = {}) {
  const silent = options.silent === true;
  try {
    const button = $(`[data-gen-slot="${slot}"]`);
    if (button) {
      button.disabled = true;
      button.innerHTML = '<span class="spinner"></span> 生成中';
    }
    await api(taskUrl('/generate/main'), { method: 'POST', json: slotPayload(slot) });
    if (!silent) toast(`第 ${slot} 张主图已生成`, 'success');
    await refreshTask();
    if (!silent) viewOutputs('main');
  } catch (error) {
    toast(error.message, 'error');
    await refreshTask();
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
  const sources = Array.from(state.detailSelection);
  if (!sources.length) {
    toast('请先选择至少一张详情原图', 'error');
    return;
  }
  try {
    const button = $('#genDetailBtn');
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> 生成中';
    await api(taskUrl('/generate/detail'), {
      method: 'POST',
      json: {
        sources,
        width: parseInt($('#detailWidth').value, 10) || 750,
        segment_height: parseInt($('#detailSegment').value, 10) || 1500,
        make_cover: $('#detailMakeCover').checked,
        cover_title: $('#detailCoverTitle').value,
        cover_subhead: $('#detailCoverSub').value,
        accent: state.global.accent,
      },
    });
    toast('详情图已生成', 'success');
    await refreshTask();
    viewOutputs('detail');
  } catch (error) {
    toast(error.message, 'error');
    await refreshTask();
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
        <button class="btn btn-primary btn-sm" id="analyzeBtn">分析关键词</button>
      </div>
      <div class="card-body">
        <label class="field"><span>商品标题（用于补充词库）</span><input id="kwProductTitle" value="${esc(draft.productTitle)}"></label>
        <textarea id="kwText" rows="6" placeholder="竞品标题一行一条，例如：高腰显瘦瑜伽裤女夏季薄款外穿打底裤">${esc(draft.text)}</textarea>
        <div class="small muted mt-8">工具不抓取淘宝站内数据；标题由你粘贴或手工填写。分析结果按词类展示，并标注来源。</div>
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
  $('#analyzeBtn').onclick = analyzeKeywords;
  $('#saveKwBtn').onclick = saveKeywords;
  renderKeywordResults();
}

function renderKeywordResults() {
  const container = $('#kwResults');
  if (!container) return;
  const analysis = state.analysis;
  if (!analysis) {
    container.innerHTML = '<div class="card"><div class="card-body alert alert-info">尚未分析。粘贴竞品标题后点击“分析关键词”。</div></div>';
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
          <div class="tc-meta">字数 ${item.length || ''} · 评分 ${item.score || 0} · ${esc(item.source || '')}</div>
        </div>
      </div>`;
  }).join('');
  const warnings = [];
  if ((analysis.bannedFound || []).length) warnings.push(`<div class="alert alert-warn">检测到敏感词：${esc(analysis.bannedFound.join('、'))}，请人工确认。</div>`);
  if ((analysis.brandFound || []).length) warnings.push(`<div class="alert alert-warn">疑似品牌词：${esc(analysis.brandFound.join('、'))}，建议从标题中去掉。</div>`);
  container.innerHTML = `
    ${warnings.join('')}
    <div class="card">
      <div class="card-head">
        <h3>分类词表 <span class="sub">点击词条可选择，蓝框为已选</span></h3>
        <button class="btn btn-secondary btn-sm" id="genTitlesBtn">用所选词生成标题</button>
      </div>
      <div class="card-body">
        <div class="grid grid-3">${categoryHtml}</div>
        <div class="small muted mt-12">分析标题 ${analysis.stats?.titleCount || 0} 条，候选词 ${analysis.stats?.wordCount || 0} 个</div>
      </div>
    </div>
    <div class="card">
      <div class="card-head"><h3>标题候选 <span class="sub">淘宝标题建议不超过 30 字，可手动编辑</span></h3></div>
      <div class="card-body">${titles || '<div class="small muted">暂无候选标题</div>'}</div>
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
      state.keywordDraft.titles[index].title = input.value;
      if (state.keywordDraft.selectedTitle === state.keywordDraft.titles[index].title) {
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
  $('#genTitlesBtn').onclick = generateTitlesFromSelection;
}

async function analyzeKeywords() {
  try {
    const button = $('#analyzeBtn');
    button.disabled = true;
    button.innerHTML = '<span class="spinner"></span> 分析中';
    const analysis = await api(taskUrl('/keywords/analyze'), {
      method: 'POST',
      json: {
        text: $('#kwText').value,
        productTitle: $('#kwProductTitle').value,
        imageTags: state.keywordDraft.imageTags,
      },
    });
    state.analysis = analysis;
    state.keywordDraft.titles = analysis.titles || [];
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
    $('#kwColorTags').textContent = colorText || '未识别到主图主色';
    toast('关键词分析完成', 'success');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function generateTitlesFromSelection() {
  try {
    const words = Array.from(state.selectedWords);
    if (!words.length) {
      toast('请先选择一些词', 'error');
      return;
    }
    const titles = await api(taskUrl('/keywords/titles'), {
      method: 'POST',
      json: { words, productTitle: state.keywordDraft.productTitle },
    });
    state.keywordDraft.titles = titles;
    state.keywordDraft.selectedTitle = titles.length ? titles[0].title : '';
    renderKeywordResults();
    toast(`已生成 ${titles.length} 条标题候选`, 'success');
  } catch (error) {
    toast(error.message, 'error');
  }
}

async function saveKeywords() {
  try {
    await api(taskUrl('/keywords/save'), { method: 'POST', json: state.keywordDraft });
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
      : { main_pc: true, main_mobile: true, white: true, detail: true, sku: true, video: true, keywords: true, meta: true };
  }
  const labels = {
    main_pc: '电脑端主图', main_mobile: '手机端主图', white: '白底图', detail: '详情页图',
    sku: 'SKU 图', video: '视频', keywords: '关键词表', meta: '商品与素材信息',
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
        <div class="alert alert-info">服务监听：${esc(settings.server?.host || '127.0.0.1')}:${esc(settings.server?.port || 8765)}（改端口需修改 config/settings.json 后重启）。</div>`,
      foot: '<button class="btn" id="setCancel">取消</button><button class="btn btn-primary" id="setSave">保存设置</button>',
      onMount: (root) => {
        $('#setCancel', root).onclick = closeModal;
        $('#setSave', root).onclick = async () => {
          const payload = { specs: {} };
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
  } catch (error) {
    toast(error.message, 'error');
  }
}

init();
