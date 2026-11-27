const el = (id) => document.getElementById(id);
const [, , taskPart, kind, slot] = location.pathname.split('/');
const taskId = decodeURIComponent(taskPart);
const variant = kind === 'main_mobile' ? 'mobile' : 'pc';
const endpoint = '/api/tasks/' + encodeURIComponent(taskId) + '/main-design/' + kind + '/' + slot;
const fields = el('studioGeometry');
const geometry = ['left', 'top', 'width', 'height'];
const assetLabels = { main: '主图', detail: '详情图', sku: 'SKU 图', review: '待确认' };
const studio = { data: null, canvas: null, objects: new Map(), buttons: new Map(), history: [], index: -1, saved: '', busy: false };
const marquee = el('studioMarquee');
let fromTemplate = false;
let templateProject = null;
let selection = null;
let draggedLayer = null;

el('studioBack').href = '/?' + new URLSearchParams({ task: taskId, slot, variant });
el('studioTitle').textContent = '第 ' + slot + ' 张主图 · ' + (variant === 'mobile' ? '手机端' : '电脑端');

function media(file, revision) {
  const url = '/media/' + encodeURIComponent(taskId) + '/' + file.split('/').map(encodeURIComponent).join('/');
  return revision ? url + '?v=' + encodeURIComponent(revision) : url;
}

async function requestDesign(payload) {
  const options = payload ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  } : {};
  const response = await fetch(endpoint, options);
  const result = await response.json();
  if (!response.ok || !result.ok) throw new Error(result.error || '读取成品失败');
  return result.data;
}

function status(message, error = false) {
  el('studioMessage').textContent = message;
  el('studioMessage').dataset.error = String(error);
}

function updateFile(data) {
  studio.data = data;
  el('studioProduct').textContent = data.title;
  const link = el('studioView');
  link.href = media(data.record.file, data.revision);
  link.classList.remove('hidden');
}

function layoutCanvas() {
  if (!studio.canvas) return;
  const { width, height } = studio.data.record.editor;
  const availableWidth = el('studioViewport').clientWidth - 32;
  const availableHeight = Math.max(250, innerHeight - el('studioViewport').getBoundingClientRect().top - 36);
  const zoom = Math.max(0.1, Math.min(1, availableWidth / width, availableHeight / height));
  studio.canvas.setZoom(zoom);
  studio.canvas.setDimensions({ width: Math.max(1, Math.floor(width * zoom)), height: Math.max(1, Math.floor(height * zoom)) });
  studio.canvas.getObjects().forEach((object) => object.setCoords());
  studio.canvas.calcOffset();
  studio.canvas.requestRenderAll();
  el('studioZoom').textContent = Math.round(zoom * 100) + '%';
  renderSelection();
}

function readGeometry(object) {
  return {
    left: Math.round(object.left),
    top: Math.round(object.top),
    width: Math.max(1, Math.round(object.width * object.scaleX)),
    height: Math.max(1, Math.round(object.height * object.scaleY)),
    opacity: Math.round(object.opacity * 100),
    asset: object.layerAsset || '',
    edits: object.layerEdits || [],
  };
}

function setGeometry(object, values) {
  const asset = values.asset || '';
  const edits = values.edits || [];
  const imageKey = edits.length ? JSON.stringify([asset, edits]) : asset;
  if (object.layerImages && object.layerImageKey !== imageKey) object.setElement(object.layerImages.get(imageKey));
  object.set({
    left: values.left, top: values.top,
    scaleX: values.width / object.width, scaleY: values.height / object.height,
    opacity: (values.opacity ?? 100) / 100,
    layerAsset: asset,
    layerEdits: edits,
    layerImageKey: imageKey,
  });
  object.setCoords();
}

function snapshot() {
  const objects = studio.canvas.getObjects();
  return JSON.stringify({
    fromTemplate,
    layers: Object.fromEntries(objects.filter((object) => object.selectable)
      .map((object) => [object.layerId, readGeometry(object)])),
    order: objects.map((object) => object.layerId),
  });
}

function setOrder(order) {
  const project = fromTemplate ? templateProject : studio.data.record.editor;
  studio.canvas.backgroundColor = 'rgb(' + project.background.join(',') + ')';
  const included = new Set(order);
  for (const object of studio.canvas.getObjects()) {
    if (!included.has(object.layerId)) {
      if (studio.canvas.getActiveObject() === object) studio.canvas.discardActiveObject();
      studio.canvas.remove(object);
    }
  }
  const existing = new Set(studio.canvas.getObjects());
  order.forEach((id, index) => {
    const object = studio.objects.get(id);
    if (!existing.has(object)) studio.canvas.add(object);
    studio.canvas.moveTo(object, index);
  });
  const list = el('studioLayersList');
  list.replaceChildren(...[...order].reverse().map((id) => studio.buttons.get(id).closest('.studio-layer-row')));
  el('studioEmptyLayers').classList.toggle('hidden', order.length > 0);
  studio.canvas.requestRenderAll();
}

function editLayer(object, focusTools = false) {
  if (studio.busy) return;
  clearSelection();
  studio.canvas.setActiveObject(object);
  studio.canvas.requestRenderAll();
  syncControls();
  if (focusTools) {
    const target = object.layerReplaceable ? el('studioCutout') : fields.elements.namedItem('width');
    target.focus();
    target.scrollIntoView({ block: 'nearest' });
  }
}

function deleteLayer(object) {
  if (studio.busy) return;
  clearSelection();
  const order = studio.canvas.getObjects().map((layer) => layer.layerId);
  setOrder(order.filter((id) => id !== object.layerId));
  remember();
  status('已移除「' + object.layerName + '」，可撤销。');
  el('studioUndo').focus();
}

function moveSelectedLayer(delta) {
  const active = studio.canvas?.getActiveObject();
  if (!active || studio.busy || selection) return;
  const order = studio.canvas.getObjects().map((object) => object.layerId);
  const index = order.indexOf(active.layerId);
  const neighbour = index + delta;
  if (neighbour < 0 || neighbour >= order.length) return;
  [order[index], order[neighbour]] = [order[neighbour], order[index]];
  setOrder(order);
  remember();
}

const layerList = el('studioLayersList');
function clearDropMarker() {
  layerList.querySelectorAll('.drop-before, .drop-after').forEach((row) =>
    row.classList.remove('drop-before', 'drop-after'));
}
layerList.addEventListener('dragstart', (event) => {
  const row = event.target.closest('[data-layer]');
  if (!row || studio.busy || selection || !row.draggable) {
    event.preventDefault();
    return;
  }
  draggedLayer = row.dataset.layer;
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', draggedLayer);
});
layerList.addEventListener('dragover', (event) => {
  const row = event.target.closest('[data-layer]');
  clearDropMarker();
  if (!draggedLayer || !row || row.dataset.layer === draggedLayer) return;
  event.preventDefault();
  const box = row.getBoundingClientRect();
  row.classList.add(event.clientY < box.top + box.height / 2 ? 'drop-before' : 'drop-after');
});
layerList.addEventListener('drop', (event) => {
  const row = event.target.closest('[data-layer]');
  if (!draggedLayer || !row || row.dataset.layer === draggedLayer || studio.busy || selection) return;
  event.preventDefault();
  const box = row.getBoundingClientRect();
  const order = studio.canvas.getObjects().map((object) => object.layerId).reverse()
    .filter((id) => id !== draggedLayer);
  const target = order.indexOf(row.dataset.layer);
  order.splice(target + (event.clientY >= box.top + box.height / 2 ? 1 : 0), 0, draggedLayer);
  setOrder(order.reverse());
  remember();
  clearDropMarker();
});
layerList.addEventListener('dragend', () => {
  draggedLayer = null;
  clearDropMarker();
});

function clearSelection() {
  const pointer = selection?.pointer;
  selection = null;
  marquee.classList.add('hidden');
  if (pointer != null && marquee.hasPointerCapture(pointer)) marquee.releasePointerCapture(pointer);
  if (studio.canvas) {
    studio.canvas.getActiveObject()?.set('hasControls', true);
    studio.canvas.requestRenderAll();
  }
}

function renderSelection() {
  const frame = el('studioMarqueeBox');
  frame.hidden = !selection?.box;
  if (!selection?.box) return;
  const { object, box, inverted } = selection;
  const image = readGeometry(object);
  const zoom = studio.canvas.getZoom();
  frame.style.left = ((image.left + box[0] * image.width) * zoom) + 'px';
  frame.style.top = ((image.top + box[1] * image.height) * zoom) + 'px';
  frame.style.width = ((box[2] - box[0]) * image.width * zoom) + 'px';
  frame.style.height = ((box[3] - box[1]) * image.height * zoom) + 'px';
  // The inverse highlight stays inside the selected product layer.
  if (inverted) {
    const left = box[0] * image.width * zoom;
    const top = box[1] * image.height * zoom;
    const right = (1 - box[2]) * image.width * zoom;
    const bottom = (1 - box[3]) * image.height * zoom;
    frame.style.clipPath = 'inset(' + [-top, -right, -bottom, -left].map((value) => value + 'px').join(' ') + ')';
  } else {
    frame.style.clipPath = '';
  }
  frame.classList.toggle('is-inverted', inverted);
}

function imagePoint(event) {
  const box = marquee.getBoundingClientRect();
  const image = readGeometry(selection.object);
  const zoom = studio.canvas.getZoom();
  return [(event.clientX - box.left) / zoom - image.left, (event.clientY - box.top) / zoom - image.top]
    .map((value, axis) => Math.max(0, Math.min(1, value / (axis === 0 ? image.width : image.height))));
}

marquee.onpointerdown = (event) => {
  if (!selection || studio.busy || selection.pointer !== null || event.button !== 0) return;
  event.preventDefault();
  selection.start = imagePoint(event);
  selection.box = null;
  selection.inverted = false;
  selection.pointer = event.pointerId;
  marquee.setPointerCapture(event.pointerId);
  renderSelection();
  syncControls();
};
function updateSelectionBox(event) {
  if (!selection || selection.pointer !== event.pointerId) return;
  const [x, y] = imagePoint(event);
  const [left, top] = selection.start;
  selection.box = [Math.min(x, left), Math.min(y, top), Math.max(x, left), Math.max(y, top)];
  renderSelection();
}
function endSelection(event) {
  if (!selection || selection.pointer !== event.pointerId) return;
  if (event.type === 'pointerup') updateSelectionBox(event);
  const { box } = selection;
  if (event.type !== 'pointerup' || !box || box[2] === box[0] || box[3] === box[1]) selection.box = null;
  selection.pointer = null;
  renderSelection();
  syncControls();
}
window.addEventListener('pointermove', updateSelectionBox);
window.addEventListener('pointerup', endSelection);
window.addEventListener('pointercancel', endSelection);
marquee.ondragstart = (event) => event.preventDefault();

async function editProduct(edit) {
  const object = studio.canvas?.getActiveObject();
  if (!object?.layerReplaceable || studio.busy) return;
  const change = readGeometry(object);
  if (change.edits.length >= 100) {
    status('本轮处理次数已达上限，请先保存成品。', true);
    return;
  }
  change.edits = [...change.edits, edit];
  studio.busy = true;
  studio.canvas.skipTargetFind = true;
  syncControls();
  status('正在处理商品图…');
  try {
    const response = await fetch(endpoint, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action: 'preview-layer', revision: studio.data.revision,
        layer: object.layerId.replace(/^template:/, ''), change, fromTemplate }),
    });
    if (!response.ok) throw new Error((await response.json()).error || '无法处理商品图');
    const url = URL.createObjectURL(await response.blob());
    try {
      const image = await loadImageUrl(url);
      object.layerImages.set(JSON.stringify([change.asset, change.edits]), image.getElement());
    } finally {
      URL.revokeObjectURL(url);
    }
    clearSelection();
    commit(object, change);
  } catch (error) {
    status(error.message, true);
  } finally {
    studio.busy = false;
    studio.canvas.skipTargetFind = false;
    syncControls();
  }
}

el('studioCutout').onclick = () => editProduct({ type: 'background' });
el('studioSelect').onclick = () => {
  if (selection) clearSelection();
  else {
    const object = studio.canvas.getActiveObject();
    selection = { object, pointer: null, box: null, inverted: false };
    object.set('hasControls', false);
    studio.canvas.requestRenderAll();
    marquee.classList.remove('hidden');
  }
  renderSelection();
  syncControls();
};
el('studioCancelSelection').onclick = () => { clearSelection(); syncControls(); };
el('studioInvert').onclick = () => {
  selection.inverted = !selection.inverted;
  renderSelection();
  syncControls();
};
el('studioClearPixels').onclick = () => editProduct({ type: selection.inverted ? 'keep' : 'clear', box: selection.box });
el('studioKeepPixels').onclick = () => editProduct({ type: selection.inverted ? 'clear' : 'keep', box: selection.box });
window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && selection && !studio.busy) { clearSelection(); syncControls(); }
});

function syncControls() {
  const active = studio.canvas?.getActiveObject();
  if (selection && selection.object !== active) clearSelection();
  const stack = studio.canvas?.getObjects() || [];
  const index = stack.indexOf(active);
  el('studioRaise').disabled = studio.busy || !!selection || index < 0 || index === stack.length - 1;
  el('studioLower').disabled = studio.busy || !!selection || index <= 0;
  el('studioPixelTools').classList.toggle('hidden', !active?.layerReplaceable);
  el('studioCutout').disabled = studio.busy || !!selection;
  el('studioSelect').disabled = studio.busy;
  el('studioSelect').setAttribute('aria-pressed', String(Boolean(selection)));
  el('studioInvert').setAttribute('aria-pressed', String(Boolean(selection?.inverted)));
  el('studioSelectionActions').classList.toggle('hidden', !selection);
  for (const id of ['studioInvert', 'studioClearPixels', 'studioKeepPixels']) {
    el(id).disabled = studio.busy || !selection?.box || selection.pointer !== null;
  }
  el('studioCancelSelection').disabled = studio.busy;
  el('studioSelectionHint').textContent = selection
    ? (selection.inverted ? '已反选：当前选中矩形外的区域。' : '在商品图上拖出矩形，粉色区域为选区。')
    : '';
  fields.classList.toggle('hidden', !active || Boolean(selection));
  el('studioSelection').textContent = active ? active.layerName : '选择图层后可调整位置和尺寸。';
  for (const [id, button] of studio.buttons) {
    button.setAttribute('aria-pressed', String(active?.layerId === id));
    button.closest('.studio-layer-row').querySelectorAll('[data-layer-action]').forEach((action) => {
      action.disabled = studio.busy;
    });
  }
  if (active) {
    const values = readGeometry(active);
    for (const key of [...geometry, 'opacity']) fields.elements.namedItem(key).value = values[key];
  }
  el('studioHelp').textContent = active?.layerStretch
    ? '拖四角等比例缩放。按住 Shift 拖四角可自由缩放，拖边缘中点可单独拉宽或拉高。'
    : '拖图层可移动。拖四角等比例缩放，按住 Shift 拖四角可自由缩放。';
  el('studioLibraryHint').textContent = active?.layerReplaceable
    ? '点击素材替换选中的商品图。'
    : '先选中商品图图层，再从这里替换素材。';
  el('studioAssets').querySelectorAll('button').forEach((button) => {
    button.disabled = studio.busy || !active?.layerReplaceable;
    button.setAttribute('aria-pressed', String(Boolean(active?.layerReplaceable && (active.layerAsset || active.layerBaseAsset) === button.dataset.asset)));
  });
  el('studioUndo').disabled = studio.busy || studio.index <= 0;
  el('studioRedo').disabled = studio.busy || studio.index >= studio.history.length - 1;
  el('studioRestore').disabled = studio.busy || !studio.canvas || fromTemplate;
  const reconstructed = studio.data?.record.editor?.reconstructed;
  el('studioSave').disabled = studio.busy || !!selection || !studio.canvas || (!hasChanges() && !reconstructed);
}

function hasChanges() {
  return studio.index >= 0 && studio.history[studio.index] !== studio.saved;
}

function remember() {
  const next = snapshot();
  if (next !== studio.history[studio.index]) {
    studio.history = studio.history.slice(0, studio.index + 1);
    studio.history.push(next);
    if (studio.history.length > 40) studio.history.shift();
    studio.index = studio.history.length - 1;
    status(hasChanges() ? '有未保存的修改' : '当前布局已保存');
  }
  syncControls();
}

function step(delta) {
  const index = studio.index + delta;
  if (studio.busy || index < 0 || index >= studio.history.length) return;
  clearSelection();
  studio.index = index;
  const saved = JSON.parse(studio.history[index]);
  fromTemplate = saved.fromTemplate;
  for (const [id, values] of Object.entries(saved.layers)) setGeometry(studio.objects.get(id), values);
  setOrder(saved.order);
  studio.canvas.requestRenderAll();
  status(hasChanges() ? '有未保存的修改' : '当前布局已保存');
  syncControls();
}

function commit(object, values) {
  const project = studio.data.record.editor;
  const limit = Math.max(project.width, project.height);
  for (const key of geometry) {
    const minimum = key === 'width' || key === 'height' ? 1 : -2 * limit;
    values[key] = Math.min(3 * limit, Math.max(minimum, values[key]));
  }
  values.opacity = Math.min(100, Math.max(0, values.opacity));
  setGeometry(object, values);
  studio.canvas.requestRenderAll();
  remember();
}

function loadImageUrl(url) {
  return new Promise((resolve, reject) => {
    fabric.Image.fromURL(url, (image, error) => {
      if (error || !image?.width) {
        reject(new Error('无法读取图层图片'));
        return;
      }
      resolve(image);
    });
  });
}

function loadPicture(file) {
  return loadImageUrl(media(file));
}
async function loadLayer(layer) {
  const image = await loadPicture(layer.file);
  const stretch = layer.name === '模板装饰';
  image.set({
    layerId: layer.id, layerName: layer.name, selectable: !layer.locked, evented: !layer.locked,
    layerReplaceable: layer.replaceable, layerBaseAsset: layer.asset || '',
    layerStretch: stretch, layerAsset: '',
    originX: 'left', originY: 'top', strokeWidth: 0, lockRotation: true,
    lockScalingFlip: true, lockSkewingX: true, lockSkewingY: true,
    transparentCorners: false, cornerColor: '#e8467c', borderColor: '#e8467c', cornerSize: 11,
  });
  image.layerImages = new Map([['', image.getElement()]]);
  image.setControlsVisibility({ mtr: false, mt: stretch, mb: stretch, ml: stretch, mr: stretch });
  setGeometry(image, { ...layer, asset: '' });
  return image;
}

function renderLibrary() {
  const group = el('studioAssetKind');
  const files = studio.data.library[group.value] || [];
  const grid = el('studioAssets');
  grid.replaceChildren();
  if (!files.length) {
    const empty = document.createElement('p');
    empty.className = 'studio-help';
    empty.textContent = '该分类暂无图片。';
    grid.append(empty);
  }
  for (const file of files) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'studio-asset';
    button.dataset.asset = file;
    button.title = file.split('/').pop();
    const image = new Image();
    image.src = media(file) + '?w=180';
    image.loading = 'lazy';
    image.alt = '';
    const name = document.createElement('span');
    name.textContent = button.title;
    button.append(image, name);
    button.onclick = () => replaceProduct(file);
    grid.append(button);
  }
  syncControls();
}

async function replaceProduct(file) {
  const object = studio.canvas.getActiveObject();
  if (!object?.layerReplaceable || studio.busy || file === (object.layerAsset || object.layerBaseAsset)) return;
  studio.busy = true;
  clearSelection();
  studio.canvas.skipTargetFind = true;
  syncControls();
  try {
    let image = object.layerImages.get(file);
    if (!image) {
      image = (await loadPicture(file)).getElement();
      object.layerImages.set(file, image);
    }
    const values = readGeometry(object);
    const scale = Math.min(values.width / image.naturalWidth, values.height / image.naturalHeight);
    const width = Math.max(1, Math.round(image.naturalWidth * scale));
    const height = Math.max(1, Math.round(image.naturalHeight * scale));
    commit(object, {
      ...values, asset: file, edits: [], width, height,
      left: values.left + Math.round((values.width - width) / 2),
      top: values.top + Math.round((values.height - height) / 2),
    });
  } catch (error) {
    status(error.message, true);
  } finally {
    studio.busy = false;
    studio.canvas.skipTargetFind = false;
    syncControls();
  }
}

async function loadProjectLayers(layers) {
  const images = await Promise.all(layers.map(loadLayer));
  for (const object of images) studio.objects.set(object.layerId, object);
  for (const layer of layers) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'studio-layer-button';
    button.disabled = layer.locked;
    button.draggable = !layer.locked;
    button.dataset.layer = layer.id;
    const thumbnail = new Image();
    thumbnail.draggable = false;
    thumbnail.src = media(layer.file);
    thumbnail.alt = '';
    const name = document.createElement('span');
    name.textContent = layer.name + (layer.locked ? ' · 已锁定' : '');
    button.title = name.textContent;
    button.append(thumbnail, name);
    const object = studio.objects.get(layer.id);
    button.onclick = () => editLayer(object);
    const row = document.createElement('div');
    row.className = 'studio-layer-row';
    row.append(button);
    if (!layer.locked) {
      const actions = document.createElement('div');
      actions.className = 'studio-layer-actions';
      for (const [label, handler] of [['编辑', () => editLayer(object, true)], ['删除', () => deleteLayer(object)]]) {
        const action = document.createElement('button');
        action.type = 'button';
        action.className = 'btn btn-sm';
        action.dataset.layerAction = label;
        action.textContent = label;
        action.setAttribute('aria-label', label + layer.name);
        action.onclick = handler;
        actions.append(action);
      }
      row.append(actions);
    }
    studio.buttons.set(layer.id, button);
  }
  return images;
}

async function show(data) {
  updateFile(data);
  const project = data.record.editor;
  const legacy = el('studioLegacy');
  if (!project) {
    legacy.src = el('studioView').href;
    legacy.classList.remove('hidden');
    el('studioPrepareBox').classList.remove('hidden');
    status('当前成品 · 原有合并图');
    return;
  }
  const images = await loadProjectLayers(project.layers);
  legacy.classList.add('hidden');
  el('studioPrepareBox').classList.add('hidden');
  el('studioDrawing').classList.remove('hidden');
  el('studioStageTools').classList.remove('hidden');
  el('studioHelp').classList.remove('hidden');
  el('studioLibrary').classList.remove('hidden');
  el('studioSize').textContent = project.width + ' × ' + project.height + ' px';
  const canvas = new fabric.Canvas('studioCanvas', {
    backgroundColor: 'rgb(' + project.background.join(',') + ')',
    preserveObjectStacking: true, selection: false, uniformScaling: true,
  });
  studio.canvas = canvas;
  setOrder(project.layers.map((layer) => layer.id));
  for (const event of ['selection:created', 'selection:updated', 'selection:cleared']) canvas.on(event, syncControls);
  canvas.on('object:modified', ({ target }) => commit(target, readGeometry(target)));
  studio.saved = snapshot();
  studio.history = [studio.saved];
  studio.index = 0;
  const first = images.find((object) => object.selectable);
  if (first) canvas.setActiveObject(first);
  const select = el('studioAssetKind');
  select.replaceChildren(...Object.entries(data.library).map(([kind, files]) =>
    new Option((assetLabels[kind] || kind) + '（' + files.length + '）', kind)));
  select.value = Object.keys(data.library).find((kind) => data.library[kind].length) || 'main';
  select.onchange = renderLibrary;
  renderLibrary();
  layoutCanvas();
  new ResizeObserver(layoutCanvas).observe(el('studioViewport'));
  window.addEventListener('resize', layoutCanvas);
  syncControls();
  status(project.reconstructed ? '已载入重建布局，保存后才会替换当前成品。' : '拖动商品图或文字标签开始编辑。');
}

fields.addEventListener('submit', (event) => event.preventDefault());
fields.addEventListener('change', (event) => {
  const object = studio.canvas?.getActiveObject();
  if (!object || studio.busy || !event.target.reportValidity()) return;
  commit(object, { ...readGeometry(object), [event.target.name]: Math.round(event.target.valueAsNumber) });
});

el('studioUndo').onclick = () => step(-1);
el('studioRedo').onclick = () => step(1);
el('studioRestore').onclick = async () => {
  if (studio.busy || fromTemplate) return;
  studio.busy = true;
  clearSelection();
  studio.canvas.skipTargetFind = true;
  syncControls();
  try {
    if (!templateProject) {
      const project = await requestDesign({ action: 'template-preview', revision: studio.data.revision });
      const layers = project.layers.map((layer) => ({ ...layer, id: 'template:' + layer.id }));
      await loadProjectLayers(layers);
      templateProject = { ...project, layers };
    }
    fromTemplate = true;
    for (const layer of templateProject.layers) setGeometry(studio.objects.get(layer.id), { ...layer, asset: '' });
    setOrder(templateProject.layers.map((layer) => layer.id));
    remember();
    status(templateProject.reconstructed
      ? '已预览旧成品的重建模板。可撤销，保存后更新成品。'
      : '已预览原模板布局。可撤销，保存后更新成品。');
  } catch (error) {
    status(error.message, true);
  } finally {
    studio.busy = false;
    studio.canvas.skipTargetFind = false;
    syncControls();
  }
};
el('studioRaise').onclick = () => moveSelectedLayer(1);
el('studioLower').onclick = () => moveSelectedLayer(-1);
el('studioPrepare').onclick = async () => {
  const button = el('studioPrepare');
  button.disabled = true;
  status('正在重建可编辑布局…');
  try {
    await show(await requestDesign({ action: 'prepare', revision: studio.data.revision }));
  } catch (error) {
    status(error.message, true);
    button.disabled = false;
  }
};
el('studioSave').onclick = async () => {
  if (studio.busy) return;
  const saved = snapshot();
  studio.busy = true;
  const active = studio.canvas.getActiveObject();
  studio.canvas.discardActiveObject();
  studio.canvas.skipTargetFind = true;
  studio.canvas.requestRenderAll();
  syncControls();
  status('正在保存成品…');
  try {
    const layout = JSON.parse(saved);
    if (layout.fromTemplate) {
      layout.order = layout.order.map((id) => id.replace(/^template:/, ''));
      layout.layers = Object.fromEntries(Object.entries(layout.layers).map(([id, values]) => [id.replace(/^template:/, ''), values]));
    }
    const kept = new Set(layout.order);
    const original = fromTemplate ? templateProject.layers.map((layer) => layer.id.replace(/^template:/, ''))
      : studio.data.record.editor.layers.map((layer) => layer.id);
    const removed = original.filter((id) => !kept.has(id));
    updateFile(await requestDesign({ revision: studio.data.revision, ...layout, removed }));
    if (layout.fromTemplate) {
      studio.saved = saved;
      location.reload();
      return;
    }
    for (const id of removed) {
      studio.objects.delete(id);
      studio.buttons.delete(id);
    }
    for (const layer of studio.data.record.editor.layers) {
      studio.buttons.get(layer.id).querySelector('img').src = media(layer.file);
      const object = studio.objects.get(layer.id);
      if (!object) continue;
      object.layerImages.set('', object.getElement());
      object.layerBaseAsset = layer.asset || '';
      object.layerAsset = '';
      object.layerEdits = [];
      object.layerImageKey = '';
    }
    studio.saved = snapshot();
    studio.history = [studio.saved];
    studio.index = 0;
    status('成品已保存。返回出图即可看到更新后的图片。');
  } catch (error) {
    status(error.message, true);
  } finally {
    studio.busy = false;
    studio.canvas.skipTargetFind = false;
    if (active) studio.canvas.setActiveObject(active);
    studio.canvas.requestRenderAll();
    syncControls();
  }
};
window.addEventListener('beforeunload', (event) => {
  if (hasChanges()) {
    event.preventDefault();
    event.returnValue = true;
  }
});
requestDesign().then(show).catch((error) => status(error.message, true));
