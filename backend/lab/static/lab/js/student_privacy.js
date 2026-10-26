const cleanedDatasetSelect = document.getElementById('cleanedDatasetSelect');
const studentIdColumn = document.getElementById('studentIdColumn');
const privacyPolicyForm = document.getElementById('privacyPolicyForm');
const privacyUnitPolicy = document.getElementById('privacyUnitPolicy');
const maxRowsField = document.getElementById('maxRowsField');
const policyStatus = document.getElementById('policyStatus');
const riskScanResult = document.getElementById('riskScanResult');
const publicBoundsFields = document.getElementById('publicBoundsFields');
let selectedDatasetProfile = null;
let defaultPublicBounds = {};

function setOptions(select, values, placeholder) {
  select.innerHTML = '';
  if (!select.multiple) {
    const prompt = document.createElement('option');
    prompt.value = '';
    prompt.textContent = placeholder;
    prompt.selected = true;
    select.appendChild(prompt);
  }
  if (!values.length) {
    if (select.multiple) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = placeholder;
      select.appendChild(option);
    }
    return;
  }
  values.forEach((value) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    if (!select.multiple && ['student_id', 'studentid', 'student_number'].includes(value.toLowerCase())) option.selected = true;
    select.appendChild(option);
  });
}

function selectedValues(select) {
  return Array.from(select.selectedOptions).map((option) => option.value);
}

async function loadSelectedDataset() {
  const datasetId = cleanedDatasetSelect.value;
  selectedDatasetProfile = null;
  document.getElementById('studentsObserved').value = '—';
  document.getElementById('rowsPerStudent').value = '—';
  setOptions(studentIdColumn, [], datasetId ? 'Loading columns…' : 'Select a dataset first');
  setOptions(document.getElementById('quasiIdentifierSelect'), [], 'No columns available');
  setOptions(document.getElementById('sensitiveAttributeSelect'), [], 'No columns available');
  publicBoundsFields.innerHTML = '<p class="muted-copy">Loading numeric columns…</p>';
  if (!datasetId) return;

  try {
    const first = await apiFetch(`/api/datasets/${datasetId}/profile/`, { method: 'GET' });
    const preferredId = (first.columns || []).find((name) => ['student_id', 'studentid', 'student_number'].includes(name.toLowerCase())) || '';
    const details = await apiFetch(`/api/datasets/${datasetId}/profile/?student_id_col=${encodeURIComponent(preferredId)}`, { method: 'GET' });
    selectedDatasetProfile = details;
    defaultPublicBounds = details.default_public_bounds || {};
    setOptions(studentIdColumn, details.columns || [], 'No columns found');
    if (preferredId) studentIdColumn.value = preferredId;
    setOptions(document.getElementById('quasiIdentifierSelect'), (details.columns || []).filter((name) => name !== studentIdColumn.value), 'No columns available');
    setOptions(document.getElementById('sensitiveAttributeSelect'), (details.columns || []).filter((name) => name !== studentIdColumn.value), 'No columns available');
    renderPublicBounds(details.profile || {});
    document.getElementById('studentsObserved').value = details.students || 'Could not identify students';
    document.getElementById('rowsPerStudent').value = details.average_rows_per_student || '—';
  } catch (error) {
    showToast(error.message, 'error');
    setOptions(studentIdColumn, [], error.message);
    publicBoundsFields.textContent = error.message;
  }
}

function renderPublicBounds(datasetProfile) {
  publicBoundsFields.innerHTML = '';
  const numericColumns = Object.entries(datasetProfile.columns || {}).filter(([column, info]) => column !== studentIdColumn.value && /^(int|float)/i.test(info.dtype));
  if (!numericColumns.length) {
    publicBoundsFields.textContent = 'This dataset has no numeric columns that need public bounds.';
    return;
  }
  numericColumns.forEach(([column]) => {
    const fallback = defaultPublicBounds[column] || ['', ''];
    const label = document.createElement('label');
    const heading = document.createElement('span');
    heading.textContent = `${column} public range`;
    const range = document.createElement('div');
    range.className = 'settings-grid';
    ['lower', 'upper'].forEach((side, index) => {
      const input = document.createElement('input');
      input.type = 'number'; input.step = 'any';
      input.placeholder = `${side[0].toUpperCase()}${side.slice(1)} bound`;
      input.value = fallback[index]; input.dataset.column = column; input.dataset.bound = side;
      range.appendChild(input);
    });
    label.append(heading, range);
    publicBoundsFields.appendChild(label);
  });
}

function collectPublicBounds() {
  const bounds = {};
  publicBoundsFields.querySelectorAll('input[data-column]').forEach((input) => {
    bounds[input.dataset.column] ||= {};
    bounds[input.dataset.column][input.dataset.bound] = input.value;
  });
  return bounds;
}

async function loadCleanedDatasets() {
  try {
    const payload = await apiFetch('/api/datasets/?stage=cleaned', { method: 'GET' });
    const datasets = payload.datasets || [];
    cleanedDatasetSelect.innerHTML = '';
    const firstOption = document.createElement('option');
    firstOption.value = '';
    firstOption.textContent = datasets.length ? 'Choose a cleaned dataset' : 'No cleaned datasets found';
    cleanedDatasetSelect.appendChild(firstOption);
    datasets.forEach((dataset) => {
      const option = document.createElement('option');
      option.value = dataset.id;
      option.textContent = `${dataset.name} · ${dataset.rows} rows`;
      cleanedDatasetSelect.appendChild(option);
    });
  } catch (error) {
    cleanedDatasetSelect.innerHTML = `<option value="">Unable to load datasets: ${error.message}</option>`;
  }
}

privacyUnitPolicy.addEventListener('change', () => {
  maxRowsField.classList.toggle('hidden', privacyUnitPolicy.value !== 'bounded');
});
cleanedDatasetSelect.addEventListener('change', loadSelectedDataset);
studentIdColumn.addEventListener('change', async () => {
  if (!cleanedDatasetSelect.value) return;
  try {
    const details = await apiFetch(`/api/datasets/${cleanedDatasetSelect.value}/profile/?student_id_col=${encodeURIComponent(studentIdColumn.value)}`, { method: 'GET' });
    selectedDatasetProfile = details;
    document.getElementById('studentsObserved').value = details.students || 'Column has no student values';
    document.getElementById('rowsPerStudent').value = details.average_rows_per_student || '—';
    renderPublicBounds(details.profile || {});
  } catch (error) {
    showToast(error.message, 'error');
  }
});

privacyPolicyForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!cleanedDatasetSelect.value || !studentIdColumn.value) {
    showToast('Choose a cleaned dataset and its student ID column.', 'error');
    return;
  }
  const saveButton = document.getElementById('savePolicyBtn');
  saveButton.disabled = true;
  policyStatus.classList.remove('hidden');
  policyStatus.textContent = 'Saving policy and scanning…';
  try {
    const payload = await apiFetch('/api/privacy-policy/', {
      method: 'POST',
      body: JSON.stringify({
        dataset_id: cleanedDatasetSelect.value,
        student_id_col: studentIdColumn.value,
        max_rows_per_student: privacyUnitPolicy.value === '1' ? 1 : Number(privacyPolicyForm.elements.max_rows_per_student.value || 1),
        quasi_identifiers: selectedValues(document.getElementById('quasiIdentifierSelect')),
        sensitive_attributes: selectedValues(document.getElementById('sensitiveAttributeSelect')),
        public_bounds: collectPublicBounds(),
      }),
    });
    const scan = payload.risk_scan;
    const minimum = scan.k_anonymity?.minimum_group_size;
    const smallCount = scan.k_anonymity?.small_cell_count ?? scan.small_cells.length;
    riskScanResult.innerHTML = '';
    [
      ['Students', scan.n_students],
      ['Minimum group size', minimum ?? 'No quasi-identifiers selected'],
      ['Groups smaller than 5', smallCount ?? 0],
    ].forEach(([label, value]) => {
      const item = document.createElement('div');
      item.className = 'summary-item';
      const title = document.createElement('span');
      title.className = 'summary-label';
      title.textContent = label;
      const content = document.createElement('strong');
      content.textContent = value;
      item.append(title, content);
      riskScanResult.appendChild(item);
    });
    const summary = document.createElement('p');
    summary.className = 'summary-item summary-wide';
    summary.textContent = scan.summary;
    riskScanResult.appendChild(summary);
    policyStatus.textContent = 'Policy saved. Risk scan complete.';
    showToast('Student-level privacy policy saved.', 'success');
  } catch (error) {
    policyStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    saveButton.disabled = false;
  }
});

loadCleanedDatasets();
