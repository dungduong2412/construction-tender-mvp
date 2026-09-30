const API = '/api';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const fmt = value => value === null || value === undefined || value === ''
  ? '—'
  : Number.isFinite(Number(value))
    ? new Intl.NumberFormat('vi-VN', {maximumFractionDigits: 4}).format(Number(value))
    : esc(value);
const categoryLabel = value => ({
  topography:'Địa hình', longitudinal_section:'Trắc dọc', cross_section:'Trắc ngang',
  geotechnical_drilling:'Khoan địa chất', sample_collection:'Lấy mẫu',
  laboratory_testing:'Thí nghiệm trong phòng', in_situ_testing:'Thí nghiệm hiện trường',
}[value] || value || 'Chưa phân nhóm');

let currentJobId = null;
let currentRows = [];
let currentRow = null;
let currentSnapshot = null;
let currentPage = 1;
let documentMeta = null;
let loadedReviewJobId = null;
let selectedReviewRowId = null;
let visibleReviewRows = [];
let estimateTab = 'approval';
let catalogue = [];
let editingCatalogueId = null;
let lastRoute = 'upload';
const collapsedGroups = new Set();
const primaryRoutes = new Set(['upload', 'review', 'estimate', 'catalogue']);

async function json(response) {
  if (!response.ok) {
    let detail;
    try { detail = await response.json(); } catch { detail = {detail: await response.text()}; }
    throw Error(typeof detail.detail === 'string' ? detail.detail : detail.detail?.message || detail.message || `HTTP ${response.status}`);
  }
  return response.json();
}

function route(name, {syncHash = true} = {}) {
  document.querySelectorAll('.page').forEach(page => page.classList.remove('active'));
  $(`page-${name}`).classList.add('active');
  document.querySelectorAll('.step[data-route]').forEach(button => button.classList.toggle('active', button.dataset.route === name));
  if (name !== 'catalogue') lastRoute = name;
  if (name === 'review' && currentJobId) loadReview();
  if (name === 'estimate' && currentJobId) loadEstimate();
  if (name === 'catalogue') loadCatalogue();
  const targetHash = name + (currentJobId && ['review', 'estimate'].includes(name) ? `/${currentJobId}` : '');
  if (syncHash && location.hash.replace('#', '') !== targetHash) location.hash = targetHash;
}

function resetJobView(jobId) {
  currentJobId = jobId;
  currentRows = [];
  currentRow = null;
  currentSnapshot = null;
  documentMeta = null;
  loadedReviewJobId = null;
  selectedReviewRowId = null;
  visibleReviewRows = [];
  currentPage = 1;
}

function applyHashRoute() {
  const [requestedName, requestedJobId] = location.hash.replace('#', '').split('/');
  const name = primaryRoutes.has(requestedName) ? requestedName : 'upload';
  const jobRoute = ['review', 'estimate'].includes(name);
  const jobChanged = Boolean(jobRoute && requestedJobId && requestedJobId !== currentJobId);
  if (jobChanged) resetJobView(requestedJobId);

  const activeName = document.querySelector('.page.active')?.id?.replace('page-', '');
  if (!jobChanged && activeName === name) return;
  if (jobRoute && !currentJobId) return route('upload', {syncHash:false});
  route(name, {syncHash:false});
}

window.addEventListener('hashchange', applyHashRoute);

document.querySelectorAll('.step[data-route]').forEach(button => button.onclick = () => route(button.dataset.route));
$('catalogue-open').onclick = () => route('catalogue');
$('catalogue-back').onclick = () => route(lastRoute === 'catalogue' ? 'upload' : lastRoute);
$('top-download').onclick = () => currentJobId ? (route('estimate'), setTimeout(downloadEstimate, 80)) : route('upload');
function status(text) { $('status-bar').textContent = text; $('status-bar').classList.add('show'); }
const jobLabel = state => ({uploaded:'Đã tải lên',parsing:'Đang đọc PDF',mapping:'Đang đối chiếu danh mục',pricing:'Đang kiểm tra đơn giá',needs_review:'Cần kiểm tra',ready:'Sẵn sàng lập dự thầu',failed:'Lỗi'}[state] || state);

$('pdf-input').onchange = event => {
  const file = event.target.files[0];
  $('file-name').textContent = file ? file.name : '';
  $('upload-btn').disabled = !file;
};
$('upload-btn').onclick = async () => {
  const file = $('pdf-input').files[0];
  const form = new FormData();
  form.append('file', file);
  $('upload-btn').disabled = true;
  try {
    let job = await json(await fetch(`${API}/jobs/upload`, {method:'POST', body:form}));
    currentJobId = job.job_id;
    for (let attempt = 0; attempt < 180; attempt += 1) {
      job = await json(await fetch(`${API}/jobs/${currentJobId}`));
      status(`${jobLabel(job.status)}…`);
      if (['ready','needs_review','failed'].includes(job.status)) {
        if (job.status === 'failed') throw Error(job.error_message || 'Xử lý thất bại');
        return openJob(currentJobId);
      }
      await new Promise(resolve => setTimeout(resolve, 600));
    }
  } catch (error) {
    status(`Không thể xử lý: ${error.message}`);
    $('upload-btn').disabled = false;
  }
};

async function loadJobs() {
  try {
    const jobs = await json(await fetch(`${API}/jobs/`));
    $('jobs-body').innerHTML = jobs.length ? jobs.map(job => `<tr><td><strong>${esc(job.filename)}</strong><br><span class="muted">${esc(job.job_id)}</span></td><td><span class="badge ${job.status === 'ready' ? 'ok' : job.status === 'failed' ? 'bad' : 'warn'}">${esc(jobLabel(job.status))}</span></td><td>${fmt(job.source_row_count ?? job.row_count)}</td><td>${fmt(job.unresolved_count)}</td><td><button class="link" data-job="${esc(job.job_id)}">Mở hồ sơ →</button></td></tr>`).join('') : '<tr><td colspan="5" class="empty">Chưa có hồ sơ.</td></tr>';
    document.querySelectorAll('[data-job]').forEach(button => button.onclick = () => openJob(button.dataset.job));
  } catch (error) {
    $('jobs-body').innerHTML = `<tr><td colspan="5">${esc(error.message)}</td></tr>`;
  }
}
$('jobs-refresh').onclick = loadJobs;

async function openJob(id) {
  currentJobId = id;
  currentSnapshot = null;
  selectedReviewRowId = null;
  loadedReviewJobId = null;
  currentPage = 1;
  await loadReview();
  route('review');
}

function rowStatus(row) {
  if (row.row_type !== 'line_item') return ['Không tính giá','','Tiêu đề / thông tin'];
  if (row.price_change_pending_review) return ['Cần duyệt lại','warn','Đơn giá danh mục đã thay đổi'];
  if (row.status === 'mapped_and_priced' && row.pricing_available) return ['Đã đối chiếu','ok','Có công việc và đơn giá'];
  if (row.status === 'mapping_ambiguous') return ['Cần xác nhận','warn','Có nhiều công việc phù hợp'];
  if (row.status === 'mapped_price_unavailable') return ['Thiếu đơn giá','bad','Đã có công việc, chưa có đơn giá'];
  return ['Chưa đối chiếu','bad','Chưa chọn được công việc phù hợp'];
}

function requiresAttention(row) {
  return row.row_type === 'line_item' && !(row.status === 'mapped_and_priced' && row.pricing_available && !row.price_change_pending_review);
}

function filteredReviewRows() {
  const query = $('review-search').value.toLowerCase().trim();
  const filter = $('review-filter').value;
  return currentRows.filter(row => {
    const matchesQuery = !query || `${row.row_number} ${row.description_vi} ${row.master_code || ''} ${row.master_description || ''}`.toLowerCase().includes(query);
    const matchesFilter = filter === 'all' || filter === 'attention' && requiresAttention(row) || filter === 'ready' && !requiresAttention(row);
    return matchesQuery && matchesFilter;
  });
}

function validPage(row) {
  return Boolean(documentMeta && Number.isInteger(Number(row?.page)) && Number(row.page) >= 1 && Number(row.page) <= Number(documentMeta.page_count || 0));
}

function hasValidSourceRegion(row) {
  if (!row || !row.azure_polygon_available || !validPage(row) || !Array.isArray(row.source_polygon) || row.source_polygon.length < 8 || row.source_polygon.length % 2 !== 0) return false;
  if (!row.source_polygon.every(value => Number.isFinite(Number(value)))) return false;
  const xs = row.source_polygon.filter((_, index) => index % 2 === 0).map(Number);
  const ys = row.source_polygon.filter((_, index) => index % 2 === 1).map(Number);
  return Math.max(...xs) > Math.min(...xs) && Math.max(...ys) > Math.min(...ys);
}

function deterministicFallback(rows) {
  return rows.find(requiresAttention) || rows.find(row => row.row_type === 'line_item') || null;
}

async function loadReview() {
  if (!currentJobId) return;
  try {
    const [rows, job, metadata] = await Promise.all([
      json(await fetch(`${API}/review/${currentJobId}/rows`)),
      json(await fetch(`${API}/jobs/${currentJobId}`)),
      json(await fetch(`${API}/jobs/${currentJobId}/document/metadata`)),
    ]);
    const changedJob = loadedReviewJobId !== currentJobId;
    currentRows = rows;
    documentMeta = metadata;
    $('review-project').textContent = job.filename;
    if (changedJob) {
      currentPage = 1;
      selectedReviewRowId = null;
      loadedReviewJobId = currentJobId;
      setPdfPage(1);
    }
    renderReview();
  } catch (error) {
    status(`Lỗi tải màn hình kiểm tra: ${error.message}`);
  }
}

function renderReview() {
  const previousSelection = selectedReviewRowId;
  visibleReviewRows = filteredReviewRows();
  if (!visibleReviewRows.some(row => row.row_id === selectedReviewRowId)) {
    selectedReviewRowId = deterministicFallback(visibleReviewRows)?.row_id || null;
  }
  $('review-tbody').innerHTML = visibleReviewRows.map(row => {
    const state = rowStatus(row);
    const billable = row.row_type === 'line_item';
    const sourceClass = hasValidSourceRegion(row) ? '' : ' source-warning';
    return `<tr data-row="${esc(row.row_id)}" class="${row.row_id === selectedReviewRowId ? 'selected' : ''}">
      <td class="${sourceClass}">${esc(row.row_number || '—')}</td>
      <td><div class="two-line" title="${esc(row.description_vi)}"><strong>${esc(row.description_vi)}</strong></div></td>
      <td>${esc(row.unit || '—')}</td><td class="numeric">${esc(row.quantity_raw || '—')}</td>
      <td><div class="two-line" title="${esc([row.master_code,row.master_description].filter(Boolean).join(' — '))}">${row.master_code ? `<strong>${esc(row.master_code)}</strong> · ${esc(row.master_description)}` : '<span class="missing">Chưa chọn</span>'}</div></td>
      <td class="numeric ${billable && !row.pricing_available ? 'missing' : ''}">${billable ? row.pricing_available ? fmt(row.unit_price) : 'Chưa có đơn giá' : '—'}</td>
      <td class="numeric">${billable ? row.pricing_available ? fmt(row.extended_amount) : '—' : '—'}</td>
      <td class="numeric">${row.confidence == null ? '—' : `${Math.round(row.confidence * 100)}%`}</td>
      <td><span class="badge ${state[1]}">${state[0]}</span></td>
      <td><div class="review-actions"><button class="ellipsis" data-evidence="${esc(row.row_id)}" title="Xem nguồn và bằng chứng">…</button><button class="btn secondary btn-edit" data-edit="${esc(row.row_id)}">Sửa</button></div></td>
    </tr>`;
  }).join('');
  document.querySelectorAll('#review-tbody tr').forEach(element => element.onclick = event => {
    if (!event.target.closest('button')) selectReviewRow(element.dataset.row, {navigate:true});
  });
  document.querySelectorAll('[data-edit]').forEach(button => button.onclick = () => openEdit(button.dataset.edit));
  document.querySelectorAll('[data-evidence]').forEach(button => button.onclick = () => openEvidence(button.dataset.evidence));
  const billableRows = currentRows.filter(row => row.row_type === 'line_item');
  const ready = billableRows.filter(row => !requiresAttention(row)).length;
  const availableSubtotal = billableRows.reduce((total, row) => total + (row.pricing_available ? Number(row.extended_amount || 0) : 0), 0);
  $('summary-bar').innerHTML = `<div class="kpi"><div class="val">${currentRows.length}</div>Dòng nguồn</div><div class="kpi"><div class="val">${billableRows.length}</div>Công việc</div><div class="kpi"><div class="val" style="color:var(--green)">${ready}</div>Đã đối chiếu</div><div class="kpi"><div class="val" style="color:var(--orange)">${billableRows.length - ready}</div>Cần kiểm tra</div><div class="kpi"><div class="val">${fmt(availableSubtotal)}</div>Tạm tính có giá</div>`;
  syncReviewSelection({navigate: previousSelection !== selectedReviewRowId});
}

function setPdfPage(page) {
  if (!documentMeta) return;
  currentPage = Math.max(1, Math.min(Number(page), Number(documentMeta.page_count || 1)));
  $('pdf-page').textContent = `${currentPage} / ${documentMeta.page_count || 1}`;
  $('pdf-image').src = `${API}/jobs/${currentJobId}/document/pages/${currentPage}.png`;
  drawHighlight(currentRows.find(row => row.row_id === selectedReviewRowId));
}

function syncReviewSelection({navigate = false} = {}) {
  document.querySelectorAll('#review-tbody tr').forEach(element => element.classList.toggle('selected', element.dataset.row === selectedReviewRowId));
  const row = currentRows.find(item => item.row_id === selectedReviewRowId);
  if (!row) {
    $('highlight-box').style.display = 'none';
    $('source-locator').classList.remove('no-source');
    $('source-locator').textContent = 'Không có dòng phù hợp trong bộ lọc hiện tại.';
    return;
  }
  if (navigate && validPage(row)) setPdfPage(row.page);
  else drawHighlight(row);
  if (hasValidSourceRegion(row)) {
    $('source-locator').classList.remove('no-source');
    $('source-locator').innerHTML = `<strong>Dòng ${esc(row.row_number || row.row_id)} · trang ${row.page}</strong><br>${esc(row.description_vi)}`;
  } else {
    $('source-locator').classList.add('no-source');
    $('source-locator').innerHTML = `<strong>Không xác định vị trí nguồn</strong><br>${esc(row.description_vi)}${validPage(row) ? ` · Trang tham chiếu ${row.page}` : ''}`;
  }
}

function selectReviewRow(rowId, options = {}) {
  if (!visibleReviewRows.some(row => row.row_id === rowId)) return;
  selectedReviewRowId = rowId;
  syncReviewSelection(options);
}

function drawHighlight(row) {
  const box = $('highlight-box');
  box.style.display = 'none';
  if (!hasValidSourceRegion(row) || Number(row.page) !== currentPage) return;
  const page = documentMeta.pages.find(item => Number(item.page) === Number(row.page));
  if (!page || !Number(page.width) || !Number(page.height)) return;
  const xs = row.source_polygon.filter((_, index) => index % 2 === 0).map(Number);
  const ys = row.source_polygon.filter((_, index) => index % 2 === 1).map(Number);
  Object.assign(box.style, {
    display:'block', left:`${Math.min(...xs) / page.width * 100}%`, top:`${Math.min(...ys) / page.height * 100}%`,
    width:`${(Math.max(...xs) - Math.min(...xs)) / page.width * 100}%`, height:`${(Math.max(...ys) - Math.min(...ys)) / page.height * 100}%`,
  });
}

$('review-search').oninput = renderReview;
$('review-filter').onchange = renderReview;
$('pdf-prev').onclick = () => setPdfPage(currentPage - 1);
$('pdf-next').onclick = () => setPdfPage(currentPage + 1);
$('pdf-image').onload = () => drawHighlight(currentRows.find(row => row.row_id === selectedReviewRowId));

function openEvidence(rowId) {
  const row = currentRows.find(item => item.row_id === rowId);
  if (!row) return;
  selectReviewRow(rowId, {navigate:true});
  $('evidence-title').textContent = `Dòng ${row.row_number || row.row_id}`;
  const audit = row.overrides?.length
    ? `<ul class="audit-list">${row.overrides.map(item => `<li><strong>${esc(item.field)}</strong>: ${esc(item.old_value || '—')} → ${esc(item.new_value)} · ${esc(item.user)}${item.created_at ? ` · ${esc(item.created_at)}` : ''}</li>`).join('')}</ul>`
    : 'Chưa có chỉnh sửa thủ công.';
  $('evidence-body').innerHTML = `<dl class="evidence-grid">
    <dt>Công việc danh mục</dt><dd>${row.master_code ? `<strong>${esc(row.master_code)}</strong> — ${esc(row.master_description)}` : 'Chưa xác định'}</dd>
    <dt>Mức phù hợp</dt><dd>${row.confidence == null ? 'Chưa có' : `${Math.round(row.confidence * 100)}%`} ${row.evidence ? `· ${esc(row.evidence)}` : ''}</dd>
    <dt>Ngày hiệu lực</dt><dd>${esc(row.price_effective_date || 'Chưa có')}</dd>
    <dt>Nguồn dòng</dt><dd>${esc(row.source_origin || 'Chưa có')} · ${validPage(row) ? `Trang ${row.page}` : 'Không có trang hợp lệ'}</dd>
    <dt>Provenance</dt><dd>${esc(row.source_provenance || 'Chưa có')}${hasValidSourceRegion(row) ? '' : '<br><span class="source-warning">Không xác định vị trí nguồn</span>'}</dd>
    <dt>Nguồn đơn giá</dt><dd>${esc(row.price_source_reference || 'Chưa có đơn giá / Not available')}</dd>
    <dt>Phiên bản / audit</dt><dd>Đối chiếu: ${esc(row.mapping_last_updated_by || row.mapped_by || 'Hệ thống')}<br>Đơn giá: ${esc(row.price_last_updated_by || 'Chưa cập nhật')}<br>${audit}</dd>
  </dl>`;
  $('evidence-modal').classList.add('open');
}

async function openEdit(rowId) {
  currentRow = currentRows.find(row => row.row_id === rowId);
  if (!currentRow) return;
  const row = currentRow;
  $('modal-desc').textContent = `Dòng ${row.row_number || row.row_id}${validPage(row) ? ` · trang nguồn ${row.page}` : ' · không xác định vị trí nguồn'}`;
  $('edit-description').value = row.description_vi || '';
  $('edit-unit').value = row.unit || '';
  $('edit-quantity').value = row.quantity_raw || '';
  $('edit-row-type').value = row.row_type;
  $('edit-section').value = row.section_path || '';
  $('modal-price-input').value = '';
  $('modal-price-source').value = row.price_source_reference || '';
  $('modal-price-effective').value = row.price_effective_date || '';
  $('modal-price-approver').value = '';
  $('modal-error').style.display = 'none';
  $('modal-provenance').innerHTML = `Nguồn: ${esc(row.source_origin)} · ${validPage(row) ? `Trang ${row.page}` : 'Không có trang hợp lệ'}<br>${hasValidSourceRegion(row) ? 'Có vùng nguồn chính xác.' : '<span class="source-warning">Không xác định vị trí nguồn</span>'}<br>Đối chiếu gần nhất: ${esc(row.mapping_last_updated_by || 'Hệ thống')}<br>${(row.overrides || []).map(item => `${esc(item.field)}: ${esc(item.old_value || '')} → ${esc(item.new_value)}`).join('<br>') || 'Chưa có chỉnh sửa thủ công.'}`;
  try {
    const candidates = await json(await fetch(`${API}/review/${currentJobId}/candidates/${encodeURIComponent(rowId)}`));
    $('modal-master-sel').innerHTML = '<option value="">Chưa xác định — cần chọn thủ công</option>' + candidates.map(item => `<option value="${item.id}" ${Number(item.id) === Number(row.master_item_id) ? 'selected' : ''}>${esc(item.item_code)} — ${esc(item.description_vi)} · ${esc(item.unit)} · ${item.unit_price == null ? 'Chưa có đơn giá' : fmt(item.unit_price)}</option>`).join('');
  } catch (error) { modalError(error.message); }
  $('modal-overlay').classList.add('open');
}

function modalError(message) { $('modal-error').textContent = message; $('modal-error').style.display = 'block'; }
function closeEdit() { $('modal-overlay').classList.remove('open'); currentRow = null; }
$('modal-close').onclick = closeEdit;
$('modal-cancel').onclick = closeEdit;
$('modal-save').onclick = async () => {
  const row = currentRow;
  const estimateWasActive = $('page-estimate').classList.contains('active');
  const fields = {description_vi:$('edit-description').value,unit:$('edit-unit').value,quantity_raw:$('edit-quantity').value,row_type:$('edit-row-type').value,section_path:$('edit-section').value,master_item_id:$('modal-master-sel').value};
  const prior = field => field === 'unit' ? row.unit : field === 'master_item_id' ? row.master_item_id : row[field];
  const changes = Object.entries(fields).filter(([field,value]) => String(value ?? '') !== String(prior(field) ?? ''));
  if ($('modal-price-input').value !== '') changes.push(['unit_price', $('modal-price-input').value]);
  try {
    for (const [field,newValue] of changes) {
      const price = field === 'unit_price';
      await json(await fetch(`${API}/review/${currentJobId}/override`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({row_id:row.row_id,field,old_value:null,new_value:String(newValue),user:'local-reviewer',price_source_reference:price ? $('modal-price-source').value : null,price_effective_date:price ? $('modal-price-effective').value : null,price_approval_status:price ? 'approved' : null,price_approved_by:price ? $('modal-price-approver').value : null,zero_price_authorized:price && $('modal-zero-authorized').checked})}));
    }
    closeEdit();
    currentSnapshot = null;
    await loadReview();
    if (estimateWasActive) await loadEstimate();
  } catch (error) { modalError(error.message); }
};

document.querySelectorAll('[data-estimate-tab]').forEach(button => button.onclick = () => {
  estimateTab = button.dataset.estimateTab;
  document.querySelectorAll('[data-estimate-tab]').forEach(item => item.classList.toggle('active', item === button));
  renderEstimate();
});

async function loadEstimate() {
  if (!currentJobId) return;
  try {
    if (loadedReviewJobId !== currentJobId) await loadReview();
    currentSnapshot = await json(await fetch(`${API}/calculation/${currentJobId}`));
    $('estimate-project').textContent = currentSnapshot.job.filename;
    renderEstimate();
  } catch (error) {
    $('estimate-rows').innerHTML = `<tr><td colspan="10">${esc(error.message)}</td></tr>`;
  }
}

function pathParts(value) {
  const text = String(value || 'Chưa phân nhóm').trim();
  for (const separator of [' > ', ' / ', '|']) if (text.includes(separator)) return text.split(separator).map(item => item.trim()).filter(Boolean);
  return [text || 'Chưa phân nhóm'];
}

function buildEstimateTree(rows) {
  const root = {key:'',code:'',label:'Dự toán',depth:0,order:Infinity,children:new Map(),rows:[]};
  const ensurePath = (parts, order) => {
    let node = root;
    let full = '';
    parts.forEach((part,index) => {
      full = full ? `${full} > ${part}` : part;
      if (!node.children.has(part)) node.children.set(part,{key:full,code:part,label:part,depth:index + 1,order,children:new Map(),rows:[]});
      node = node.children.get(part);
      node.order = Math.min(node.order, order);
    });
    return node;
  };
  rows.forEach(row => {
    const order = Number(row.doc_order || 0);
    const parts = pathParts(row.section);
    if (row.row_type === 'line_item') ensurePath(parts, order).rows.push(row);
    else {
      const hierarchicalCode = /^[IVXLCDM]+(?:\.\d+)*$/i.test(String(row.row_number || ''));
      if (row.row_type === 'heading' || hierarchicalCode) {
        const node = ensurePath(parts, order);
        node.code = row.row_number || node.code;
        node.label = row.description || node.label;
        node.structuralRow = row;
      }
    }
  });
  const sortNode = node => {
    node.rows.sort((a,b) => Number(a.doc_order) - Number(b.doc_order));
    node.children = new Map([...node.children.entries()].sort((a,b) => a[1].order - b[1].order));
    node.children.forEach(sortNode);
  };
  sortNode(root);
  return root;
}

function hierarchyLookup(root) {
  const lookup = new Map();
  const visit = (node, parents = []) => {
    for (const child of node.children || []) {
      const path = [...parents, child.name];
      if (child.kind === 'group') lookup.set(path.join(' > '), child);
      visit(child, path);
    }
  };
  visit(root || {children:[]});
  return lookup;
}

function estimateValues(row) {
  if (estimateTab === 'approval') {
    const detail = row.approval_detail || {};
    const available = detail.calculation_status === 'resolved' && row.quantity != null;
    const material = available ? Number(detail.direct_material_unit) : null;
    const labour = available ? Number(detail.direct_labour_unit) : null;
    const machine = available ? Number(detail.direct_machine_unit) : null;
    const unitPrice = available ? material + labour + machine : null;
    return {available,material,labour,machine,unitPrice,amount:available ? unitPrice * Number(row.quantity) : null};
  }
  const available = Boolean(row.pricing_available && row.tender_unit_price != null && row.quantity != null);
  return {available,material:null,labour:null,machine:null,unitPrice:available ? Number(row.tender_unit_price) : null,amount:available ? Number(row.tender_amount) : null};
}

function renderEstimateNode(node, backendGroups) {
  const key = `${estimateTab}:${node.key}`;
  const collapsed = collapsedGroups.has(key);
  const backend = backendGroups.get(node.key);
  const subtotal = backend?.partial_subtotal ?? null;
  const incomplete = backend ? backend.status !== 'COMPLETE' : false;
  const level = Math.min(node.depth, 3);
  let html = `<tr class="group-row level-${level}" data-group-row="${esc(node.key)}"><td><button class="group-toggle" data-toggle-group="${esc(node.key)}">${collapsed ? '▸' : '▾'}</button><span class="group-code">${esc(node.code)}</span></td><td colspan="7">${esc(node.label)} ${incomplete ? '<span class="status-note">• Chưa đầy đủ</span>' : ''}</td><td class="numeric">${subtotal == null ? 'Chưa có đơn giá' : fmt(subtotal)}</td><td>${node.structuralRow?.source_origin === 'manual_entry' ? `<button class="btn secondary small" data-estimate-edit="${esc(node.structuralRow.row_id)}">Sửa</button>` : ''}</td></tr>`;
  if (!collapsed) {
    for (const row of node.rows) {
      const value = estimateValues(row);
      const removeLabel = row.source_origin === 'manual_entry' ? 'Xóa' : 'Loại';
      html += `<tr class="estimate-detail indent-${level}" data-estimate-row="${esc(row.row_id)}"><td>${esc(row.row_number || '')}</td><td><div class="work-label"><strong>${esc(row.description)}</strong>${row.mapped_work_item ? `<br><span class="muted">${esc(row.mapped_work_item)} · ${esc(row.master_description || '')}</span>` : ''}</div></td><td>${esc(row.unit || '')}</td><td class="numeric">${fmt(row.quantity)}</td><td class="numeric">${value.material == null ? '—' : fmt(value.material)}</td><td class="numeric">${value.labour == null ? '—' : fmt(value.labour)}</td><td class="numeric">${value.machine == null ? '—' : fmt(value.machine)}</td><td class="numeric ${value.unitPrice == null ? 'missing' : ''}">${value.unitPrice == null ? 'Chưa có đơn giá' : fmt(value.unitPrice)}</td><td class="numeric ${value.amount == null ? 'missing' : ''}">${value.amount == null ? '—' : fmt(value.amount)}</td><td><div class="row-actions"><button class="btn secondary small" data-estimate-edit="${esc(row.row_id)}">Sửa</button><button class="btn danger small" data-exclude-row="${esc(row.row_id)}">${removeLabel}</button></div></td></tr>`;
    }
    node.children.forEach(child => { html += renderEstimateNode(child, backendGroups); });
  }
  html += `<tr class="subtotal-row" data-subtotal-group="${esc(node.key)}"><td></td><td colspan="7">Cộng ${esc(node.code || node.label)}${incomplete ? ' — Chưa đầy đủ' : ''}</td><td class="numeric">${subtotal == null ? 'Chưa có đơn giá' : fmt(subtotal)}</td><td></td></tr>`;
  return html;
}

function renderEstimate() {
  if (!currentSnapshot) return;
  const branch = currentSnapshot[estimateTab];
  const approval = estimateTab === 'approval';
  const incomplete = branch.status !== 'COMPLETE';
  $('estimate-title').textContent = approval ? 'Phê duyệt nội bộ' : 'Dự thầu';
  $('draft-warn').classList.toggle('show', incomplete);
  $('estimate-status').textContent = incomplete ? 'DRAFT / INCOMPLETE' : 'Đầy đủ';
  $('estimate-status').className = `badge ${incomplete ? 'warn' : 'ok'}`;
  const detailRows = currentSnapshot.rows.filter(row => row.row_type === 'line_item');
  const priced = detailRows.filter(row => estimateValues(row).available).length;
  $('estimate-summary').innerHTML = `<div class="summary-cell"><div class="value">${detailRows.length}</div><div class="label">Số hạng mục</div></div><div class="summary-cell"><div class="value" style="color:var(--green)">${priced}</div><div class="label">Đã có giá / đủ căn cứ</div></div><div class="summary-cell"><div class="value" style="color:var(--orange)">${detailRows.length - priced}</div><div class="label">Chưa có giá</div></div><div class="summary-cell"><div class="value">${fmt(branch.partial_subtotal)}</div><div class="label">Tổng tạm tính có giá</div></div>`;
  const tree = buildEstimateTree(currentSnapshot.rows);
  const groups = hierarchyLookup(branch.hierarchy);
  let html = '';
  tree.children.forEach(node => { html += renderEstimateNode(node, groups); });
  html += `<tr class="grand-row"><td></td><td colspan="7">TỔNG CỘNG ${incomplete ? '— DRAFT / INCOMPLETE' : ''}</td><td class="numeric">${branch.official_total == null ? 'Chưa đủ điều kiện xác lập' : fmt(branch.official_total)}</td><td></td></tr>`;
  $('estimate-rows').innerHTML = html || '<tr><td colspan="10" class="empty">Chưa có hạng mục.</td></tr>';
  $('estimate-bottom').innerHTML = `<div><strong>${detailRows.length - priced} hạng mục chưa đầy đủ</strong><br><span class="muted">Tổng tạm tính chỉ bao gồm dữ liệu có căn cứ. Giá trị thiếu không được thay bằng 0.</span></div><div class="bottom-total">Tạm tính có giá: ${fmt(branch.partial_subtotal)}</div>`;
  $('estimate-audit').innerHTML = `Mã lần tính: <strong>${esc(currentSnapshot.snapshot_id)}</strong> · Phiên bản công thức: ${esc(currentSnapshot.formula_version?.version_id)} · ${currentSnapshot.counts.mandatory_unresolved} dòng thiếu giá dự thầu · ${currentSnapshot.counts.approval_evidence_unresolved} dòng thiếu căn cứ phê duyệt. Mọi thay đổi dòng được lưu trong lịch sử kiểm tra.`;
  document.querySelectorAll('[data-toggle-group]').forEach(button => button.onclick = () => {
    const key = `${estimateTab}:${button.dataset.toggleGroup}`;
    collapsedGroups.has(key) ? collapsedGroups.delete(key) : collapsedGroups.add(key);
    renderEstimate();
  });
  document.querySelectorAll('[data-estimate-edit]').forEach(button => button.onclick = () => openEdit(button.dataset.estimateEdit));
  document.querySelectorAll('[data-exclude-row]').forEach(button => button.onclick = () => excludeEstimateRow(button.dataset.excludeRow));
}

async function excludeEstimateRow(rowId) {
  const row = currentRows.find(item => item.row_id === rowId);
  if (!row || !confirm(row.source_origin === 'manual_entry' ? 'Xóa dòng khỏi bản kê? Lịch sử chỉnh sửa vẫn được lưu.' : 'Loại dòng nguồn này khỏi bản kê làm việc? Dòng PDF và provenance vẫn được giữ nguyên.')) return;
  await json(await fetch(`${API}/review/${currentJobId}/override`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({row_id:rowId,field:'row_type',old_value:row.row_type,new_value:'metadata',user:'local-reviewer'})}));
  currentSnapshot = null;
  await loadReview();
  await loadEstimate();
}

function downloadEstimate() {
  if (currentJobId && currentSnapshot) location.href = `${API}/export/${currentJobId}/estimate.xlsx?view=${estimateTab}&snapshot_id=${encodeURIComponent(currentSnapshot.snapshot_id)}`;
}
$('dl-btn').onclick = downloadEstimate;
function openAddRow(type) {
  $('row-error').style.display = 'none';
  $('row-type').value = type;
  $('row-modal-title').textContent = type === 'heading' ? 'Thêm nhóm / tiểu nhóm' : 'Thêm dòng vào bản kê';
  $('row-unit').disabled = type === 'heading';
  $('row-quantity').disabled = type === 'heading';
  $('row-modal').classList.add('open');
}
$('add-row').onclick = () => openAddRow('line_item');
$('add-section').onclick = () => openAddRow('heading');
$('row-type').onchange = () => openAddRow($('row-type').value);
document.querySelectorAll('[data-close]').forEach(button => button.onclick = () => $(button.dataset.close).classList.remove('open'));
$('row-save').onclick = async () => {
  try {
    const rowType = $('row-type').value;
    const sectionPath = $('row-section').value;
    const groupCode = sectionPath.replace(' / ', ' > ').split(' > ').pop().trim();
    await json(await fetch(`${API}/review/${currentJobId}/rows`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({description_vi:$('row-description').value,row_number:rowType === 'heading' ? groupCode : null,unit:$('row-unit').value,quantity_raw:$('row-quantity').value,section_path:sectionPath,row_type:rowType,user:'local-reviewer'})}));
    $('row-modal').classList.remove('open');
    currentSnapshot = null;
    await loadReview();
    await loadEstimate();
  } catch (error) { $('row-error').textContent = error.message; $('row-error').style.display = 'block'; }
};

async function loadCatalogue() {
  try {
    const data = await json(await fetch(`${API}/admin/master-data`));
    catalogue = data.catalogue || [];
    const categories = [...new Set(catalogue.map(item => item.category).filter(Boolean))].sort();
    $('catalogue-category').innerHTML = '<option value="">Tất cả nhóm</option>' + categories.map(value => `<option value="${esc(value)}">${esc(categoryLabel(value))}</option>`).join('');
    renderCatalogue();
  } catch (error) { $('catalogue-body').innerHTML = `<tr><td colspan="8">${esc(error.message)}</td></tr>`; }
}

function renderCatalogue() {
  const query = $('catalogue-search').value.toLowerCase();
  const category = $('catalogue-category').value;
  const state = $('catalogue-status').value;
  const items = catalogue.filter(item => (state === 'all' || item.status === state) && (!category || item.category === category) && (!query || `${item.code} ${item.name_vi} ${item.name_en || ''} ${item.long_description || ''} ${(item.aliases || []).join(' ')}`.toLowerCase().includes(query)));
  $('catalogue-body').innerHTML = items.length ? items.map(item => `<tr class="${item.status === 'retired' ? 'retired' : ''}"><td><strong>${esc(item.code)}</strong></td><td><strong>${esc(item.name_vi)}</strong>${item.name_en ? `<br><span class="muted">${esc(item.name_en)}</span>` : ''}</td><td>${esc(item.long_description || '')}<br><span class="muted">${esc((item.aliases || []).join(', '))}</span></td><td>${esc(categoryLabel(item.category))}<br>${esc(item.unit)}</td><td>${item.pricing_available ? fmt(item.unit_price) : '<span class="missing">Chưa có đơn giá</span>'}</td><td>${esc(item.source_reference || 'Chưa có nguồn')}<br><span class="muted">Hiệu lực: ${esc(item.price_effective_date || 'Chưa có')}</span></td><td><span class="badge ${item.status === 'active' ? 'ok' : ''}">${item.status === 'active' ? 'Đang sử dụng' : 'Ngừng sử dụng'}</span></td><td><button class="btn secondary small" data-edit-cat="${item.id}">Sửa</button> ${item.status === 'active' ? `<button class="btn danger small" data-retire-cat="${item.id}">Xóa</button>` : ''}</td></tr>`).join('') : '<tr><td colspan="8" class="empty">Không có mục phù hợp.</td></tr>';
  document.querySelectorAll('[data-edit-cat]').forEach(button => button.onclick = () => openCat(Number(button.dataset.editCat)));
  document.querySelectorAll('[data-retire-cat]').forEach(button => button.onclick = () => retireCat(Number(button.dataset.retireCat)));
}

$('catalogue-search').oninput = renderCatalogue;
$('catalogue-category').onchange = renderCatalogue;
$('catalogue-status').onchange = renderCatalogue;
$('catalogue-add').onclick = () => openCat(null);
function openCat(id) {
  editingCatalogueId = id;
  const item = catalogue.find(value => value.id === id) || {};
  $('catalogue-modal-title').textContent = id ? 'Sửa công việc' : 'Thêm công việc';
  $('catalogue-error').style.display = 'none';
  const fields = {code:item.code || '',nameVi:item.name_vi || '',nameEn:item.name_en || '',description:item.long_description || '',aliases:(item.aliases || []).join(', '),category:item.category || '',unit:item.unit || '',price:item.unit_price ?? '',effective:item.price_effective_date || '',source:item.source_reference || '',approver:item.approved_by || '',status:item.status || 'active'};
  Object.entries(fields).forEach(([key,value]) => { $(`cat-${key.replace(/[A-Z]/g, match => `-${match.toLowerCase()}`)}`).value = value; });
  $('catalogue-modal').classList.add('open');
}

$('catalogue-save').onclick = async () => {
  const body = {code:$('cat-code').value,name_vi:$('cat-name-vi').value,name_en:$('cat-name-en').value || null,long_description:$('cat-description').value,aliases:$('cat-aliases').value.split(',').map(value => value.trim()).filter(Boolean),category:$('cat-category').value,unit:$('cat-unit').value,unit_price:$('cat-price').value === '' ? null : $('cat-price').value,source_reference:$('cat-source').value || null,effective_date:$('cat-effective').value || null,approval_status:'approved',approved_by:$('cat-approver').value || null,status:$('cat-status').value,actor:'local-admin'};
  try {
    await json(await fetch(`${API}/admin/master-data/catalogue${editingCatalogueId ? `/${editingCatalogueId}` : ''}`, {method:editingCatalogueId ? 'PATCH' : 'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
    $('catalogue-modal').classList.remove('open');
    loadCatalogue();
  } catch (error) { $('catalogue-error').textContent = error.message; $('catalogue-error').style.display = 'block'; }
};

async function retireCat(id) {
  if (confirm('Ngừng sử dụng mục này? Các hồ sơ đã tham chiếu vẫn được giữ nguyên.')) {
    await json(await fetch(`${API}/admin/master-data/catalogue/${id}?actor=local-admin`, {method:'DELETE'}));
    loadCatalogue();
  }
}

fetch('/health').then(json).then(health => $('environment-badge').textContent = (health.environment || 'local').toUpperCase()).catch(() => {});
loadJobs();
applyHashRoute();
