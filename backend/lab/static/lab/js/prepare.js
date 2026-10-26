const uploadZone = document.getElementById('uploadZone');
const uploadInput = document.getElementById('uploadInput');
const selectFileBtn = document.getElementById('selectFileBtn');
const clearFileBtn = document.getElementById('clearFileBtn');
const fileMeta = document.getElementById('fileMeta');
const uploadBtn = document.getElementById('uploadBtn');
const cleanBtn = document.getElementById('cleanBtn');
const uploadProgressBlock = document.getElementById('uploadProgressBlock');
const uploadProgressBar = document.getElementById('uploadProgressBar');
const uploadPercentText = document.getElementById('uploadPercentText');
const profileTableBody = document.getElementById('profileTableBody');
const cleanSummaryCard = document.getElementById('cleanSummaryCard');
const downloadCleanedBtn = document.getElementById('downloadCleanedBtn');
const beforeRows = document.getElementById('beforeRows');
const afterRows = document.getElementById('afterRows');
const missingCells = document.getElementById('missingCells');
const changeLogList = document.getElementById('changeLogList');
const simulatedDatasetSelect = document.getElementById('simulatedDatasetSelect');
const attachDatasetBtn = document.getElementById('attachDatasetBtn');
const refreshDatasetsBtn = document.getElementById('refreshDatasetsBtn');
const datasetListStatus = document.getElementById('datasetListStatus');

let uploadedDatasetId = null;
let cleanedDatasetId = null;

function updateMeta(file) {
  if (!file) {
    fileMeta.innerHTML = '<span class="meta-label">No file selected</span>';
    return;
  }

  fileMeta.innerHTML = `
    <span class="meta-label">Selected file</span>
    <strong>${file.name}</strong>
    <span>${(file.size / 1024 / 1024).toFixed(2)} MB</span>
  `;
}

function setUploadProgress(percent) {
  uploadProgressBlock.classList.remove('hidden');
  uploadProgressBar.style.width = `${percent}%`;
  uploadPercentText.textContent = `${percent}%`;
}

function renderProfile(profile) {
  profileTableBody.innerHTML = '';
  const columns = profile.columns || {};

  Object.entries(columns).forEach(([name, details]) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${name}</td>
      <td>${details.dtype}</td>
      <td>${details.missing_pct}%</td>
      <td>${details.unique_count}</td>
      <td>${details.mean !== undefined ? `mean=${details.mean.toFixed(2)}` : (details.top_values ? Object.entries(details.top_values).slice(0, 2).map(([k, v]) => `${k}:${v}`).join(', ') : '—')}</td>
      <td>${details.is_identifier ? '<span class="badge badge-danger">Possible identifier</span>' : '<span class="badge badge-pass">OK</span>'}</td>
    `;
    profileTableBody.appendChild(row);
  });
}

async function loadDatasetList() {
  if (datasetListStatus) datasetListStatus.textContent = 'Loading available source files…';
  try {
    const response = await apiFetch('/api/datasets/', { method: 'GET' });
    const options = (response.datasets || []).filter((item) => ['raw', 'simulated'].includes(item.stage));
    const optionElements = [];
    options.forEach((item) => {
      const option = document.createElement('option');
      option.value = item.id;
      option.textContent = `${item.name} · ${item.stage} · ${item.rows} rows`;
      optionElements.push(option);
    });
    simulatedDatasetSelect.replaceChildren(
      new Option(options.length ? 'Choose source data' : 'No uploaded or generated source data found', ''),
      ...optionElements,
    );
    if (datasetListStatus) datasetListStatus.textContent = options.length
      ? `${options.length} source file(s) available.`
      : 'Upload a CSV or generate source data on the previous page.';
  } catch (error) {
    console.error(error);
    if (datasetListStatus) datasetListStatus.textContent = `Could not refresh the list: ${error.message}. Showing any source files already loaded.`;
  }
}

async function handleUpload() {
  const file = uploadInput.files[0];
  if (!file) {
    showToast('Choose a CSV file first.', 'error');
    return;
  }

  const formData = new FormData();
  formData.append('file', file);

  try {
    uploadBtn.disabled = true;
    setUploadProgress(20);
    const response = await fetch('/api/upload/', {
      method: 'POST',
      body: formData,
      credentials: 'same-origin',
      headers: {
        'X-CSRFToken': getCookie('csrftoken'),
      },
    });

    setUploadProgress(80);
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || 'Upload failed.');
    }

    uploadedDatasetId = payload.dataset_id;
    renderProfile(payload.profile);
    setUploadProgress(100);
    showToast('Dataset uploaded and profiled.', 'success');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    uploadBtn.disabled = false;
    setTimeout(() => uploadProgressBlock.classList.add('hidden'), 800);
  }
}

async function handleClean() {
  const datasetId = uploadedDatasetId || simulatedDatasetSelect.value;
  if (!datasetId) {
    showToast('Upload a dataset or select a simulated one first.', 'error');
    return;
  }

  const options = {
    drop_duplicate_rows: document.getElementById('dropDuplicateRows').checked,
    drop_identifier_columns: document.getElementById('dropIdentifierColumns').checked,
    normalize_category_case: document.getElementById('normalizeCategoryCase').checked,
    missing_numeric_policy: document.getElementById('missingNumericPolicy').value,
    missing_categorical_policy: document.getElementById('missingCategoricalPolicy').value,
    outlier_strategy: document.getElementById('outlierStrategy').value,
    missing_threshold: Number(document.getElementById('missingThreshold').value || 0.8),
    privacy_unit_key: document.getElementById('privacyUnitKey').value || 'student_id',
  };

  try {
    cleanBtn.disabled = true;
    const response = await apiFetch('/api/clean/', {
      method: 'POST',
      body: JSON.stringify({ dataset_id: datasetId, options }),
    });

    const profile = response.profile || { columns: {} };
    renderProfile(profile);
    cleanSummaryCard.classList.remove('hidden');
    beforeRows.textContent = response.report.before_rows;
    afterRows.textContent = response.report.after_rows;
    missingCells.textContent = response.report.missing_cells || 0;
    changeLogList.innerHTML = '';
    (response.report.changes || []).forEach((entry) => {
      const item = document.createElement('li');
      item.textContent = entry;
      changeLogList.appendChild(item);
    });
    downloadCleanedBtn.href = `/api/datasets/${response.dataset_id}/download/`;
    cleanedDatasetId = response.dataset_id;
    showToast('Cleaning completed successfully.', 'success');
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    cleanBtn.disabled = false;
  }
}

attachDatasetBtn.addEventListener('click', () => {
  const datasetId = simulatedDatasetSelect.value;
  if (!datasetId) {
    showToast('Select a dataset to attach.', 'error');
    return;
  }

  uploadedDatasetId = datasetId;
  showToast('Dataset selected for cleaning.', 'success');
});
if (refreshDatasetsBtn) refreshDatasetsBtn.addEventListener('click', loadDatasetList);

if (selectFileBtn && uploadInput) selectFileBtn.addEventListener('click', () => uploadInput.click());
if (clearFileBtn && uploadInput) clearFileBtn.addEventListener('click', () => { uploadInput.value = ''; updateMeta(null); });
if (uploadBtn) uploadBtn.addEventListener('click', handleUpload);
cleanBtn.addEventListener('click', handleClean);
if (uploadInput) uploadInput.addEventListener('change', (event) => {
  const file = event.target.files[0];
  updateMeta(file);
});

if (uploadZone && uploadInput) uploadZone.addEventListener('click', () => uploadInput.click());
if (uploadZone && uploadInput) uploadZone.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault();
    uploadInput.click();
  }
});

['dragenter', 'dragover'].forEach((eventName) => {
  if (!uploadZone) return;
  uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    uploadZone.classList.add('dragover');
  });
});

['dragleave', 'drop'].forEach((eventName) => {
  if (!uploadZone) return;
  uploadZone.addEventListener(eventName, (event) => {
    event.preventDefault();
    uploadZone.classList.remove('dragover');
  });
});

if (uploadZone && uploadInput) uploadZone.addEventListener('drop', (event) => {
  const file = event.dataTransfer.files[0];
  if (file) {
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    uploadInput.files = dataTransfer.files;
    updateMeta(file);
  }
});

loadDatasetList();
