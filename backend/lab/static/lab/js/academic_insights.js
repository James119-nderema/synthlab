const insightsDatasetSelect = document.getElementById('insightsDatasetSelect');
const insightsGroupSelect = document.getElementById('insightsGroupSelect');
const insightsMetricSelect = document.getElementById('insightsMetricSelect');
const insightsStatus = document.getElementById('insightsStatus');
const runInsightsBtn = document.getElementById('runInsightsBtn');
const insightDatasets = new Map();
let insightsRunning = false;

function clearInsights() {
  ['insightsRecordCount', 'insightsMean', 'insightsMedian', 'insightsRange'].forEach((id) => {
    document.getElementById(id).textContent = '—';
  });
  document.getElementById('insightsDescription').textContent = '';
  document.getElementById('insightsTableBody').innerHTML = '<tr><td colspan="4">Generate insights to see group summaries.</td></tr>';
}

function fillSelect(select, placeholder, values, preferred = '') {
  select.replaceChildren();
  const initial = document.createElement('option');
  initial.value = '';
  initial.textContent = placeholder;
  select.appendChild(initial);
  values.forEach((value) => {
    const option = document.createElement('option');
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
  select.disabled = !values.length;
  if (values.includes(preferred)) select.value = preferred;
  else if (values.length) select.value = values[0];
}

async function loadInsightsOptions() {
  const datasetId = insightsDatasetSelect.value;
  clearInsights();
  fillSelect(insightsGroupSelect, 'Choose a grouping column', []);
  fillSelect(insightsMetricSelect, 'Choose a numeric outcome', []);
  if (!datasetId) return;
  try {
    const options = await apiFetch(`/api/academic-insights/?synthetic_id=${encodeURIComponent(datasetId)}`, { method: 'GET' });
    fillSelect(insightsGroupSelect, 'Choose a grouping column', options.categorical_columns);
    fillSelect(insightsMetricSelect, 'Choose a numeric outcome', options.numeric_columns,
      options.numeric_columns.find((column) => /score|grade|gpa|exam/i.test(column)) || '');
    const privacy = options.privacy;
    document.getElementById('insightsEpsilon').textContent = privacy.epsilon == null ? 'Unavailable' : Number(privacy.epsilon).toPrecision(4);
    document.getElementById('insightsDelta').textContent = privacy.delta == null ? 'Unavailable' : Number(privacy.delta).toExponential(2);
    document.getElementById('insightsEpsilonSpent').textContent = Number(privacy.epsilon_spent).toPrecision(4);
    document.getElementById('insightsAccountant').textContent = privacy.accountant;
    insightsStatus.textContent = `${options.dataset.name} · ${options.dataset.rows} generated records. Choose a group and outcome to summarize.`;
  } catch (error) {
    insightsStatus.textContent = error.message;
  }
}

function renderInsights(result) {
  const format = (value) => Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 });
  document.getElementById('insightsRecordCount').textContent = Number(result.records).toLocaleString();
  document.getElementById('insightsMean').textContent = format(result.mean);
  document.getElementById('insightsMedian').textContent = format(result.median);
  document.getElementById('insightsRange').textContent = `${format(result.min)} – ${format(result.max)}`;
  document.getElementById('insightsDescription').textContent = `${result.metric_column} summarized by ${result.group_column} from ${result.dataset}. Group means use synthetic records only.`;
  const body = document.getElementById('insightsTableBody');
  body.replaceChildren();
  result.groups.forEach((group) => {
    const row = document.createElement('tr');
    [group.group, Number(group.count).toLocaleString(), format(group.mean), group.median == null ? '—' : format(group.median)]
      .forEach((value, index) => {
        const cell = document.createElement(index === 0 ? 'th' : 'td');
        cell.textContent = value;
        row.appendChild(cell);
      });
    body.appendChild(row);
  });
}

insightsDatasetSelect.addEventListener('change', loadInsightsOptions);
runInsightsBtn.addEventListener('click', async () => {
  if (insightsRunning) return;
  const syntheticId = insightsDatasetSelect.value;
  const groupColumn = insightsGroupSelect.value;
  const metricColumn = insightsMetricSelect.value;
  if (!syntheticId || !groupColumn || !metricColumn) {
    insightsStatus.textContent = 'Choose a dataset, grouping column, and numeric outcome first.';
    showToast('Complete all insight selections first.', 'error');
    return;
  }
  insightsRunning = true;
  runInsightsBtn.disabled = true;
  runInsightsBtn.textContent = 'Analyzing…';
  insightsStatus.textContent = 'Summarizing the selected DP synthetic output…';
  try {
    const result = await apiFetch('/api/academic-insights/', {
      method: 'POST',
      body: JSON.stringify({ synthetic_id: syntheticId, group_column: groupColumn, metric_column: metricColumn }),
    });
    renderInsights(result);
    insightsStatus.textContent = 'Insights generated from synthetic records.';
    showToast('Academic insights generated.', 'success');
  } catch (error) {
    insightsStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    insightsRunning = false;
    runInsightsBtn.disabled = false;
    runInsightsBtn.textContent = 'Generate insights';
  }
});

async function loadInsightDatasets() {
  const response = await apiFetch('/api/datasets/?stage=synthetic&dp=true', { method: 'GET' });
  const datasets = (response.datasets || []).filter((dataset) => dataset.source_dataset_id);
  insightsDatasetSelect.innerHTML = '<option value="">Choose a DP synthetic dataset</option>';
  datasets.forEach((dataset) => {
    insightDatasets.set(dataset.id, dataset);
    const option = document.createElement('option');
    option.value = dataset.id;
    option.textContent = `${dataset.name} · source: ${dataset.source_dataset_name}`;
    insightsDatasetSelect.appendChild(option);
  });
  insightsStatus.textContent = datasets.length
    ? 'Select a DP synthetic output to load its columns and privacy parameters.'
    : 'No DP outputs with linked cleaned sources are available. Complete the DP generator first.';
}

loadInsightDatasets().catch((error) => {
  insightsStatus.textContent = error.message;
  insightsDatasetSelect.innerHTML = '<option value="">Could not load DP outputs</option>';
});
