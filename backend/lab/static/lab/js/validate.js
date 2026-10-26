const validateDatasetSelect = document.getElementById('datasetSelect');
const validateBtn = document.getElementById('validateBtn');
const scoreValue = document.getElementById('scoreValue');
const detailsList = document.getElementById('detailsList');
const validationStatus = document.getElementById('validationStatus');
const comparisonValue = document.getElementById('comparisonValue');
let validationInProgress = false;

async function loadValidationOptions() {
  const payload = await apiFetch('/api/datasets/?stage=synthetic&dp=true', { method: 'GET' });
  const datasets = payload.datasets || [];
  validateDatasetSelect.innerHTML = '<option value="">Choose a dataset</option>';
  const validDatasets = datasets.filter((dataset) => dataset.source_dataset_id);
  validDatasets.forEach((dataset) => {
    const option = document.createElement('option');
    option.value = dataset.id;
    option.textContent = `${dataset.name} · source: ${dataset.source_dataset_name}`;
    validateDatasetSelect.appendChild(option);
  });
  if (!validDatasets.length) {
    validateDatasetSelect.options[0].textContent = 'No DP synthetic datasets with a source found';
    validationStatus.textContent = 'No DP output is available to compare yet. Train the DP generator first.';
  } else {
    validationStatus.textContent = 'Each output is compared with the cleaned source dataset used to create it.';
  }
}

validateDatasetSelect.addEventListener('change', () => {
  if (validateDatasetSelect.value) {
    validationStatus.textContent = 'Ready to compare this DP output with its cleaned source dataset.';
  }
});

validateBtn.addEventListener('click', async () => {
  if (validationInProgress) return;
  const datasetId = validateDatasetSelect.value;
  if (!datasetId) {
    validationStatus.textContent = 'Choose a DP synthetic dataset from the dropdown first.';
    showToast('Choose a dataset to validate.', 'error');
    return;
  }

  validationInProgress = true;
  validateBtn.disabled = true;
  validateBtn.textContent = 'Validating…';
  validationStatus.textContent = 'Comparing source and synthetic distributions…';
  try {
    const payload = await apiFetch('/api/validate/', {
      method: 'POST',
      body: JSON.stringify({ dataset_id: datasetId }),
    });

    scoreValue.textContent = Number(payload.score || 0).toFixed(2);
    comparisonValue.textContent = `${payload.synthetic.name} (${payload.synthetic.rows} rows) vs ${payload.source.name} (${payload.source.rows} rows)`;
    detailsList.innerHTML = '';
    const entries = payload.details || {};
    Object.entries(entries).forEach(([label, value]) => {
      if (label === 'score') return;
      const item = document.createElement('li');
      item.textContent = typeof value === 'object' ? `${label}: ${JSON.stringify(value)}` : `${label}: ${value}`;
      detailsList.appendChild(item);
    });

    validationStatus.textContent = 'Validation completed. The score summarizes the least similar measured column; it is a fidelity indicator, not a privacy guarantee.';
    showToast('Validation completed.', 'success');
  } catch (error) {
    validationStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    validationInProgress = false;
    validateBtn.disabled = false;
    validateBtn.textContent = 'Run validation';
  }
});

loadValidationOptions().catch((error) => {
  validationStatus.textContent = error.message;
  validateDatasetSelect.innerHTML = '<option value="">Could not load DP datasets</option>';
});
