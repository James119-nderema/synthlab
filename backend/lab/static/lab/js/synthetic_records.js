const syntheticDatasetSelect = document.getElementById('syntheticDatasetSelect');
const syntheticRecordsStatus = document.getElementById('syntheticRecordsStatus');
const downloadSyntheticRecords = document.getElementById('downloadSyntheticRecords');
const syntheticPreviewHead = document.getElementById('syntheticPreviewHead');
const syntheticPreviewBody = document.getElementById('syntheticPreviewBody');

async function loadPrivateOutputs() {
  try {
    const result = await apiFetch('/api/datasets/?stage=synthetic&dp=true', { method: 'GET' });
    const datasets = result.datasets || [];
    syntheticDatasetSelect.innerHTML = '';
    const prompt = document.createElement('option'); prompt.value = ''; prompt.textContent = datasets.length ? 'Choose a DP synthetic dataset' : 'No DP synthetic datasets yet'; syntheticDatasetSelect.appendChild(prompt);
    datasets.forEach((dataset) => {
      const option = document.createElement('option'); option.value = dataset.id; option.textContent = `${dataset.name} · ${dataset.rows} rows`; syntheticDatasetSelect.appendChild(option);
    });
    syntheticRecordsStatus.textContent = datasets.length ? 'Only outputs from the DP generator are listed here.' : 'Train the DP generator first to create synthetic records.';
  } catch (error) {
    syntheticRecordsStatus.textContent = error.message;
    syntheticDatasetSelect.innerHTML = '<option value="">Could not load synthetic datasets</option>';
  }
}

syntheticDatasetSelect.addEventListener('change', async () => {
  const id = syntheticDatasetSelect.value;
  if (!id) return;
  try {
    const result = await apiFetch(`/api/datasets/${id}/preview/`, { method: 'GET' });
    syntheticPreviewHead.innerHTML = '';
    syntheticPreviewBody.innerHTML = '';
    const heading = document.createElement('tr');
    result.columns.forEach((column) => { const cell = document.createElement('th'); cell.textContent = column; heading.appendChild(cell); });
    syntheticPreviewHead.appendChild(heading);
    result.preview.forEach((record) => {
      const row = document.createElement('tr');
      result.columns.forEach((column) => { const cell = document.createElement('td'); cell.textContent = record[column] ?? '—'; row.appendChild(cell); });
      syntheticPreviewBody.appendChild(row);
    });
    downloadSyntheticRecords.href = result.download_url;
    downloadSyntheticRecords.classList.remove('hidden');
    syntheticRecordsStatus.textContent = `${result.dataset.name} · ${result.dataset.rows} records · ${result.dataset.cols} columns`;
  } catch (error) {
    syntheticRecordsStatus.textContent = error.message;
    showToast(error.message, 'error');
  }
});

loadPrivateOutputs();
