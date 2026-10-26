const modelDatasetSelect = document.getElementById('modelDatasetSelect');
const modelTargetSelect = document.getElementById('modelTargetSelect');
const trainModelBtn = document.getElementById('trainModelBtn');
const modelStatus = document.getElementById('modelStatus');
const modelDatasets = new Map();
let modelTraining = false;

function resetModelResults() {
  document.getElementById('syntheticModelScore').textContent = '—';
  document.getElementById('realModelScore').textContent = '—';
  document.getElementById('modelScoreGap').textContent = '—';
  document.getElementById('modelHoldoutStudents').textContent = '—';
  document.getElementById('modelRunDetails').textContent = '';
}

async function loadModelDatasets() {
  const response = await apiFetch('/api/datasets/?stage=synthetic&dp=true', { method: 'GET' });
  const datasets = (response.datasets || []).filter((item) => item.source_dataset_id);
  modelDatasetSelect.innerHTML = '<option value="">Choose a DP synthetic dataset</option>';
  datasets.forEach((dataset) => {
    modelDatasets.set(dataset.id, dataset);
    const option = document.createElement('option');
    option.value = dataset.id;
    option.textContent = `${dataset.name} · source: ${dataset.source_dataset_name}`;
    modelDatasetSelect.appendChild(option);
  });
  modelStatus.textContent = datasets.length
    ? 'Select an output. Its linked cleaned source will be used automatically.'
    : 'No DP synthetic outputs with a linked cleaned source are available. Complete the DP generator first.';
}

async function loadModelTargets() {
  const dataset = modelDatasets.get(modelDatasetSelect.value);
  modelTargetSelect.disabled = true;
  modelTargetSelect.innerHTML = '<option value="">Loading targets…</option>';
  resetModelResults();
  if (!dataset) {
    modelTargetSelect.innerHTML = '<option value="">Choose a dataset first</option>';
    return;
  }
  try {
    const profile = await apiFetch(`/api/datasets/${dataset.source_dataset_id}/profile/`, { method: 'GET' });
    const columns = Object.entries(profile.profile?.columns || {})
      .filter(([name, info]) => !info.is_identifier && name !== 'student_id')
      .map(([name]) => name);
    modelTargetSelect.innerHTML = '<option value="">Choose a target</option>';
    columns.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      modelTargetSelect.appendChild(option);
    });
    modelTargetSelect.disabled = !columns.length;
    modelStatus.textContent = columns.length
      ? `Source: ${dataset.source_dataset_name}. Both models will use the same student-level real holdout.`
      : 'No eligible target columns were found in the cleaned source.';
  } catch (error) {
    modelTargetSelect.innerHTML = '<option value="">Could not load targets</option>';
    modelStatus.textContent = error.message;
  }
}

modelDatasetSelect.addEventListener('change', loadModelTargets);

trainModelBtn.addEventListener('click', async () => {
  if (modelTraining) return;
  const syntheticId = modelDatasetSelect.value;
  const target = modelTargetSelect.value;
  const model = document.getElementById('modelSelect').value;
  if (!syntheticId || !target) {
    modelStatus.textContent = 'Choose a DP dataset and target first.';
    showToast('Choose a dataset and target first.', 'error');
    return;
  }
  modelTraining = true;
  trainModelBtn.disabled = true;
  trainModelBtn.textContent = 'Training…';
  modelStatus.textContent = 'Training both models and scoring them on held-out students…';
  try {
    const result = await apiFetch('/api/analytics-model/train/', {
      method: 'POST',
      body: JSON.stringify({ synthetic_id: syntheticId, target, model }),
    });
    const isAccuracy = result.metric === 'accuracy';
    const formatScore = (score) => isAccuracy ? `${(Number(score) * 100).toFixed(1)}%` : Number(score).toFixed(3);
    const gap = Number(result.gap);
    document.getElementById('syntheticMetricLabel').textContent = `Synthetic-trained ${result.metric}`;
    document.getElementById('realMetricLabel').textContent = `Real-trained ${result.metric}`;
    document.getElementById('gapMetricLabel').textContent = `${result.metric} gap`;
    document.getElementById('syntheticModelScore').textContent = formatScore(result.synthetic_score);
    document.getElementById('realModelScore').textContent = formatScore(result.real_score);
    document.getElementById('modelScoreGap').textContent = isAccuracy
      ? `${gap >= 0 ? '+' : ''}${(gap * 100).toFixed(1)} pp`
      : `${gap >= 0 ? '+' : ''}${gap.toFixed(3)}`;
    document.getElementById('modelHoldoutStudents').textContent = result.test_students;
    document.getElementById('modelRunDetails').textContent = `${result.model} · ${result.target} · ${result.synthetic} trained on synthetic data; ${result.source} trained on real data. Evaluated on ${result.test_rows} real rows from ${result.test_students} held-out students, with ${result.feature_count} shared features.`;
    modelStatus.textContent = 'Training and comparison completed.';
    showToast('Model comparison completed.', 'success');
  } catch (error) {
    modelStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    modelTraining = false;
    trainModelBtn.disabled = false;
    trainModelBtn.textContent = 'Train and compare';
  }
});

loadModelDatasets().catch((error) => {
  modelStatus.textContent = error.message;
  modelDatasetSelect.innerHTML = '<option value="">Could not load DP datasets</option>';
});
