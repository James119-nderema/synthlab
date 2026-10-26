const utilityDatasetSelect = document.getElementById('utilityDatasetSelect');
const utilityTargetSelect = document.getElementById('utilityTargetSelect');
const runUtilityBtn = document.getElementById('runUtilityBtn');
const utilityStatus = document.getElementById('utilityStatus');
const utilityComparison = document.getElementById('utilityComparison');
const utilityDetails = document.getElementById('utilityDetails');
const sweepTableBody = document.getElementById('sweepTableBody');
const utilityDatasetById = new Map();
let utilityRunInProgress = false;

function resetUtilityResult(message = 'Choose a DP synthetic dataset and run the evaluation.') {
  document.getElementById('utilityEpsilon').textContent = '—';
  document.getElementById('utilityScore').textContent = '—';
  document.getElementById('utilityTstr').textContent = '—';
  document.getElementById('utilityBaseline').textContent = '—';
  utilityComparison.textContent = '';
  utilityDetails.innerHTML = `<li>${message}</li>`;
  sweepTableBody.innerHTML = `<tr><td colspan="5">${message}</td></tr>`;
}

async function loadUtilityDatasets() {
  const payload = await apiFetch('/api/datasets/?stage=synthetic&dp=true', { method: 'GET' });
  const datasets = (payload.datasets || []).filter((dataset) => dataset.source_dataset_id);
  utilityDatasetSelect.innerHTML = '<option value="">Choose a DP synthetic dataset</option>';
  datasets.forEach((dataset) => {
    utilityDatasetById.set(dataset.id, dataset);
    const option = document.createElement('option');
    option.value = dataset.id;
    option.textContent = `${dataset.name} · source: ${dataset.source_dataset_name}`;
    utilityDatasetSelect.appendChild(option);
  });
  utilityStatus.textContent = datasets.length
    ? 'Select an output. Its linked cleaned source will be used automatically.'
    : 'No DP synthetic datasets with a linked cleaned source are available. Train the DP generator first.';
}

async function loadUtilityTargets() {
  const dataset = utilityDatasetById.get(utilityDatasetSelect.value);
  utilityTargetSelect.innerHTML = '<option value="">Loading numeric targets…</option>';
  utilityTargetSelect.disabled = true;
  if (!dataset?.source_dataset_id) return;
  try {
    const profile = await apiFetch(`/api/datasets/${dataset.source_dataset_id}/profile/`, { method: 'GET' });
    const targets = Object.entries(profile.profile?.columns || {})
      .filter(([, info]) => /^(int|float)/i.test(info.dtype) && !info.is_identifier)
      .map(([name]) => name);
    utilityTargetSelect.innerHTML = '<option value="">Choose a numeric target</option>';
    targets.forEach((target) => {
      const option = document.createElement('option');
      option.value = target;
      option.textContent = target;
      utilityTargetSelect.appendChild(option);
    });
    if (targets.includes('gpa')) utilityTargetSelect.value = 'gpa';
    utilityTargetSelect.disabled = !targets.length;
    utilityStatus.textContent = targets.length
      ? `Source: ${dataset.source_dataset_name}. Choose an outcome to measure train-on-synthetic, test-on-real performance.`
      : 'The linked source has no numeric target columns for TSTR evaluation.';
  } catch (error) {
    utilityTargetSelect.innerHTML = '<option value="">Could not load numeric targets</option>';
    utilityStatus.textContent = error.message;
  }
}

utilityDatasetSelect.addEventListener('change', () => {
  resetUtilityResult();
  if (!utilityDatasetSelect.value) {
    utilityTargetSelect.innerHTML = '<option value="">Choose a dataset first</option>';
    utilityTargetSelect.disabled = true;
    return;
  }
  loadUtilityTargets();
});

runUtilityBtn.addEventListener('click', async () => {
  if (utilityRunInProgress) return;
  const syntheticId = utilityDatasetSelect.value;
  const target = utilityTargetSelect.value;
  if (!syntheticId || !target) {
    utilityStatus.textContent = 'Choose a DP synthetic dataset and numeric target first.';
    showToast('Choose a dataset and target first.', 'error');
    return;
  }

  utilityRunInProgress = true;
  runUtilityBtn.disabled = true;
  runUtilityBtn.textContent = 'Evaluating…';
  utilityStatus.textContent = 'Comparing distributions and evaluating predictions on held-out real rows…';
  try {
    const response = await apiFetch('/api/utility-evaluation/', {
      method: 'POST',
      body: JSON.stringify({ synthetic_id: syntheticId, target }),
    });
    const result = response.result;
    const tstr = result.tstr_r2 == null ? 'Not defined' : Number(result.tstr_r2).toFixed(3);
    const delta = Number(result.utility_vs_baseline);
    const verdict = result.utility_score >= 0.8 ? 'Strong fidelity' : result.utility_score >= 0.6 ? 'Review fidelity' : 'Low fidelity';

    document.getElementById('utilityEpsilon').textContent = response.epsilon == null ? 'Unavailable' : Number(response.epsilon).toFixed(3);
    document.getElementById('utilityScore').textContent = Number(result.utility_score).toFixed(3);
    document.getElementById('utilityTstr').textContent = tstr;
    document.getElementById('utilityBaseline').textContent = `${delta >= 0 ? '+' : ''}${delta.toFixed(3)} (baseline ${Number(result.baseline_score).toFixed(3)})`;
    utilityComparison.textContent = `${response.synthetic.name} (${response.synthetic.rows} rows) compared with ${response.source.name} (${response.source.rows} rows). Target: ${result.target}.`;

    sweepTableBody.innerHTML = '';
    const row = document.createElement('tr');
    [response.epsilon == null ? '—' : Number(response.epsilon).toFixed(3),
      Number(result.utility_score).toFixed(3), `${delta >= 0 ? '+' : ''}${delta.toFixed(3)}`,
      tstr, result.target].forEach((value) => {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.appendChild(cell);
    });
    sweepTableBody.appendChild(row);

    utilityDetails.innerHTML = '';
    Object.entries(result.fidelity_details || {}).forEach(([column, details]) => {
      if (column === 'score' || column === 'rows' || column === 'columns') return;
      const item = document.createElement('li');
      item.textContent = `${column}: ${JSON.stringify(details)}`;
      utilityDetails.appendChild(item);
    });
    utilityStatus.textContent = `${verdict}. TSTR uses synthetic rows for training and a held-out 20% of real rows for testing.`;
    showToast('Utility evaluation completed.', 'success');
  } catch (error) {
    utilityStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    utilityRunInProgress = false;
    runUtilityBtn.disabled = false;
    runUtilityBtn.textContent = 'Run utility evaluation';
  }
});

loadUtilityDatasets().catch((error) => {
  utilityStatus.textContent = error.message;
  utilityDatasetSelect.innerHTML = '<option value="">Could not load DP datasets</option>';
});
