const predictionDatasetSelect = document.getElementById('predictionDatasetSelect');
const predictionTargetSelect = document.getElementById('predictionTargetSelect');
const predictionStatus = document.getElementById('predictionStatus');
const evaluatePredictionsBtn = document.getElementById('evaluatePredictionsBtn');
const predictionDatasets = new Map();
let predictionEvaluationRunning = false;

function clearPredictionResults() {
  document.getElementById('predictionSyntheticScore').textContent = '—';
  document.getElementById('predictionRealScore').textContent = '—';
  document.getElementById('predictionStudents').textContent = '—';
  document.getElementById('predictionRows').textContent = '—';
  document.getElementById('predictionDetails').textContent = '';
  document.getElementById('classificationResults').hidden = true;
  document.getElementById('regressionResults').hidden = true;
}

async function loadPredictionDatasets() {
  const response = await apiFetch('/api/datasets/?stage=synthetic&dp=true', { method: 'GET' });
  const datasets = (response.datasets || []).filter((dataset) => dataset.source_dataset_id);
  predictionDatasetSelect.innerHTML = '<option value="">Choose a DP synthetic dataset</option>';
  datasets.forEach((dataset) => {
    predictionDatasets.set(dataset.id, dataset);
    const option = document.createElement('option');
    option.value = dataset.id;
    option.textContent = `${dataset.name} · source: ${dataset.source_dataset_name}`;
    predictionDatasetSelect.appendChild(option);
  });
  predictionStatus.textContent = datasets.length
    ? 'Select an output to use its linked cleaned source for comparison.'
    : 'No DP outputs with linked cleaned sources are available. Complete the DP generator first.';
}

async function loadPredictionTargets() {
  const dataset = predictionDatasets.get(predictionDatasetSelect.value);
  predictionTargetSelect.disabled = true;
  predictionTargetSelect.innerHTML = '<option value="">Loading targets…</option>';
  clearPredictionResults();
  if (!dataset) {
    predictionTargetSelect.innerHTML = '<option value="">Choose a dataset first</option>';
    return;
  }
  try {
    const profile = await apiFetch(`/api/datasets/${dataset.source_dataset_id}/profile/`, { method: 'GET' });
    const columns = Object.entries(profile.profile?.columns || {})
      .filter(([name, info]) => !info.is_identifier && name !== 'student_id')
      .map(([name]) => name);
    predictionTargetSelect.innerHTML = '<option value="">Choose a target</option>';
    columns.forEach((name) => {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      predictionTargetSelect.appendChild(option);
    });
    predictionTargetSelect.disabled = !columns.length;
    predictionStatus.textContent = columns.length
      ? `Source: ${dataset.source_dataset_name}. Evaluation uses a shared student-level holdout.`
      : 'No eligible targets were found in the cleaned source.';
  } catch (error) {
    predictionTargetSelect.innerHTML = '<option value="">Could not load targets</option>';
    predictionStatus.textContent = error.message;
  }
}

function renderConfusionMatrix(container, labels, matrix) {
  const table = document.createElement('table');
  table.className = 'data-table';
  const head = document.createElement('thead');
  const headerRow = document.createElement('tr');
  ['Actual / predicted', ...labels].forEach((label) => {
    const cell = document.createElement('th');
    cell.textContent = label;
    headerRow.appendChild(cell);
  });
  head.appendChild(headerRow);
  table.appendChild(head);
  const body = document.createElement('tbody');
  matrix.forEach((values, index) => {
    const row = document.createElement('tr');
    const labelCell = document.createElement('th');
    labelCell.textContent = labels[index];
    row.appendChild(labelCell);
    values.forEach((value) => {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.appendChild(cell);
    });
    body.appendChild(row);
  });
  table.appendChild(body);
  container.replaceChildren(table);
}

function metricRow(label, precision, recall, f1) {
  const row = document.createElement('tr');
  [label, precision, recall, f1].forEach((value, index) => {
    const cell = document.createElement(index ? 'td' : 'th');
    cell.textContent = index ? `${(Number(value) * 100).toFixed(1)}%` : value;
    row.appendChild(cell);
  });
  return row;
}

function renderPredictionResult(result) {
  const isClassification = result.metric === 'accuracy';
  const formatScore = (value) => isClassification ? `${(Number(value) * 100).toFixed(1)}%` : Number(value).toFixed(3);
  document.getElementById('syntheticScoreLabel').textContent = `Synthetic-trained ${result.metric}`;
  document.getElementById('realScoreLabel').textContent = `Real-trained ${result.metric}`;
  document.getElementById('predictionSyntheticScore').textContent = formatScore(result.synthetic_score);
  document.getElementById('predictionRealScore').textContent = formatScore(result.real_score);
  document.getElementById('predictionStudents').textContent = result.test_students;
  document.getElementById('predictionRows').textContent = result.test_rows;
  document.getElementById('predictionDetails').textContent = `${result.model} · ${result.target} · ${result.source} and ${result.synthetic} · ${result.feature_count} shared input features.`;

  if (isClassification) {
    const body = document.getElementById('classificationMetricsBody');
    body.replaceChildren(
      metricRow('Synthetic-trained', result.synthetic_precision, result.synthetic_recall, result.synthetic_f1),
      metricRow('Real-trained', result.real_precision, result.real_recall, result.real_f1),
    );
    renderConfusionMatrix(document.getElementById('syntheticConfusion'), result.labels, result.synthetic_confusion_matrix);
    renderConfusionMatrix(document.getElementById('realConfusion'), result.labels, result.real_confusion_matrix);
    document.getElementById('classificationResults').hidden = false;
  } else {
    const body = document.getElementById('regressionMetricsBody');
    body.replaceChildren();
    [['Synthetic-trained', result.synthetic_mae, result.synthetic_rmse], ['Real-trained', result.real_mae, result.real_rmse]]
      .forEach(([name, mae, rmse]) => {
        const row = document.createElement('tr');
        [name, Number(mae).toFixed(3), Number(rmse).toFixed(3)].forEach((value, index) => {
          const cell = document.createElement(index ? 'td' : 'th');
          cell.textContent = value;
          row.appendChild(cell);
        });
        body.appendChild(row);
      });
    document.getElementById('regressionResults').hidden = false;
  }
}

predictionDatasetSelect.addEventListener('change', loadPredictionTargets);
evaluatePredictionsBtn.addEventListener('click', async () => {
  if (predictionEvaluationRunning) return;
  const syntheticId = predictionDatasetSelect.value;
  const target = predictionTargetSelect.value;
  const model = document.getElementById('predictionModelSelect').value;
  if (!syntheticId || !target) {
    predictionStatus.textContent = 'Choose a DP dataset and target first.';
    showToast('Choose a dataset and target first.', 'error');
    return;
  }
  predictionEvaluationRunning = true;
  evaluatePredictionsBtn.disabled = true;
  evaluatePredictionsBtn.textContent = 'Evaluating…';
  predictionStatus.textContent = 'Training both models and evaluating predictions on held-out students…';
  clearPredictionResults();
  try {
    const result = await apiFetch('/api/analytics-model/train/', {
      method: 'POST',
      body: JSON.stringify({ synthetic_id: syntheticId, target, model }),
    });
    renderPredictionResult(result);
    predictionStatus.textContent = 'Evaluation completed on the shared real student holdout.';
    showToast('Prediction evaluation completed.', 'success');
  } catch (error) {
    predictionStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    predictionEvaluationRunning = false;
    evaluatePredictionsBtn.disabled = false;
    evaluatePredictionsBtn.textContent = 'Train and evaluate';
  }
});

loadPredictionDatasets().catch((error) => {
  predictionStatus.textContent = error.message;
  predictionDatasetSelect.innerHTML = '<option value="">Could not load DP datasets</option>';
});
