const dpSourceDatasetSelect = document.getElementById('datasetSelect');
const sourceDatasetStatus = document.getElementById('sourceDatasetStatus');
const trainGeneratorBtn = document.getElementById('trainGeneratorBtn');
const trainingResultCard = document.getElementById('trainingResultCard');

async function loadCleanedSourceDatasets() {
  try {
    const payload = await apiFetch('/api/datasets/?stage=cleaned', { method: 'GET' });
    const datasets = payload.datasets || [];
    dpSourceDatasetSelect.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = datasets.length ? 'Choose a cleaned dataset' : 'No cleaned datasets found';
    dpSourceDatasetSelect.appendChild(placeholder);
    datasets.forEach((dataset) => {
      const option = document.createElement('option');
      option.value = dataset.id;
      option.textContent = `${dataset.name} · ${dataset.rows} rows`;
      dpSourceDatasetSelect.appendChild(option);
    });
    sourceDatasetStatus.textContent = datasets.length
      ? 'Select the cleaned dataset with its saved student-level privacy policy.'
      : 'Clean a source dataset in Data Preprocessing before continuing.';
  } catch (error) {
    dpSourceDatasetSelect.innerHTML = '<option value="">Could not load cleaned datasets</option>';
    sourceDatasetStatus.textContent = error.message;
  }
}

dpSourceDatasetSelect.addEventListener('change', () => {
  trainGeneratorBtn.disabled = !dpSourceDatasetSelect.value;
  trainingResultCard.classList.add('hidden');
});

trainGeneratorBtn.addEventListener('click', async () => {
  if (!dpSourceDatasetSelect.value) return;
  trainGeneratorBtn.disabled = true;
  trainGeneratorBtn.textContent = 'Training…';
  sourceDatasetStatus.textContent = 'Computing private aggregates and sampling synthetic records…';
  try {
    const result = await apiFetch('/api/dp-generator/train/', {
      method: 'POST',
      body: JSON.stringify({
        dataset_id: dpSourceDatasetSelect.value,
        n_rows: Number(document.getElementById('rowCountInput').value || 500),
        seed: Number(document.getElementById('seedInput').value || 42),
      }),
    });
    trainingResultCard.innerHTML = '';
    const heading = document.createElement('h2');
    heading.textContent = 'DP synthetic dataset created';
    const summary = document.createElement('p');
    summary.className = 'muted-copy';
    summary.textContent = `${result.privacy.method} · student-level (ε=${result.privacy.epsilon}, δ=${result.privacy.delta})`;
    const grid = document.createElement('div'); grid.className = 'summary-grid';
    [[`Rows`, result.rows], ['Columns', result.columns.length], ['Privacy unit', result.privacy.privacy_unit], ['Students used', result.privacy.students_used], ['Marginal length', result.privacy.reporting_length]].forEach(([label, value]) => {
      const item = document.createElement('div'); item.className = 'summary-item';
      const key = document.createElement('span'); key.className = 'summary-label'; key.textContent = label;
      const val = document.createElement('strong'); val.textContent = value;
      item.append(key, val); grid.appendChild(item);
    });
    const actions = document.createElement('div'); actions.className = 'card-actions';
    const download = document.createElement('a'); download.href = result.download_url; download.className = 'btn btn-secondary'; download.textContent = 'Download synthetic CSV';
    const next = document.createElement('a'); next.href = '/synthetic-records/'; next.className = 'btn btn-primary'; next.textContent = 'Review synthetic records';
    actions.append(download, next);
    trainingResultCard.append(heading, summary, grid, actions);
    trainingResultCard.classList.remove('hidden');
    sourceDatasetStatus.textContent = 'Training complete. The DP budget was recorded against this dataset.';
    showToast('DP synthetic dataset created.', 'success');
  } catch (error) {
    sourceDatasetStatus.textContent = error.message.includes('Public lower and upper bounds')
      ? `${error.message} Go to Define Student-Level Privacy, enter the dataset's public score range, and save the policy before training.`
      : error.message;
    showToast(error.message, 'error');
  } finally {
    trainGeneratorBtn.disabled = !dpSourceDatasetSelect.value;
    trainGeneratorBtn.textContent = 'Train DP generator';
  }
});

loadCleanedSourceDatasets();
