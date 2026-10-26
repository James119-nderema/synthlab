const privacySyntheticSelect = document.getElementById('privacySyntheticSelect');
const privacyRunBtn = document.getElementById('privacyRunBtn');
const privacyRunMessage = document.getElementById('privacyRunMessage');
const privacyReportCard = document.getElementById('privacyReportCard');
const privacyStatus = document.getElementById('privacyStatus');
const privacyRiskBadge = document.getElementById('privacyRiskBadge');
const exactMatchValue = document.getElementById('exactMatchValue');
const dcrSummary = document.getElementById('dcrSummary');
const dcrBaseline = document.getElementById('dcrBaseline');
const aucValue = document.getElementById('aucValue');
const privacyExplanation = document.getElementById('privacyExplanation');
const recommendationList = document.getElementById('recommendationList');
const reasonList = document.getElementById('reasonList');
const exportReportBtn = document.getElementById('exportReportBtn');
const privacyHistogram = document.getElementById('privacyHistogram');
const privacyComparedDatasets = document.getElementById('privacyComparedDatasets');
let privacyRunInProgress = false;

async function loadPrivacyOptions() {
  const payload = await apiFetch('/api/datasets/?stage=synthetic&dp=true', { method: 'GET' });
  const datasets = (payload.datasets || []).filter((dataset) => dataset.source_dataset_id);
  privacySyntheticSelect.innerHTML = '<option value="">Choose a DP synthetic dataset</option>';
  datasets.forEach((dataset) => {
    const option = document.createElement('option');
    option.value = dataset.id;
    option.textContent = `${dataset.name} · source: ${dataset.source_dataset_name}`;
    privacySyntheticSelect.appendChild(option);
  });
  privacyRunMessage.textContent = datasets.length
    ? 'The source dataset is linked to each generated output and will be selected automatically.'
    : 'No DP synthetic outputs with a linked cleaned source are available yet.';
}

function renderHistogram(jobResult) {
  const dcr = jobResult?.dcr || jobResult?.result?.dcr || {};
  const synthetic = Number(dcr.median || 0);
  const baseline = Number(dcr.baseline?.median || 0);
  const maxValue = Math.max(synthetic, baseline, 1);

  privacyHistogram.innerHTML = '';
  const bars = [
    { label: 'Synthetic→Real (median)', value: synthetic, color: '#7c3aed' },
    { label: 'Real baseline (median)', value: baseline, color: '#22c55e' },
  ];

  bars.forEach((bar) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'histogram-bar-wrap';
    const label = document.createElement('span');
    label.textContent = bar.label;
    const barTrack = document.createElement('div');
    barTrack.className = 'histogram-track';
    const inner = document.createElement('div');
    inner.className = 'histogram-fill';
    inner.style.width = `${Math.min(100, (bar.value / maxValue) * 100)}%`;
    inner.style.background = bar.color;
    barTrack.appendChild(inner);
    wrapper.appendChild(label);
    wrapper.appendChild(barTrack);
    privacyHistogram.appendChild(wrapper);
  });
}

function renderReport(result) {
  privacyReportCard.classList.remove('hidden');
  privacyStatus.textContent = result.risk_level || 'Unknown';
  privacyRiskBadge.textContent = result.verdict || 'Unknown';
  privacyRiskBadge.dataset.level = (result.risk_level || 'Low').toLowerCase();

  exactMatchValue.textContent = `${Number(result.exact_match_pct || 0).toFixed(2)}%`;
  dcrSummary.textContent = `min ${Number(result.dcr?.min || 0).toFixed(4)} · p05 ${Number(result.dcr?.p05 || 0).toFixed(4)} · median ${Number(result.dcr?.median || 0).toFixed(4)}`;
  dcrBaseline.textContent = `baseline: min ${Number(result.dcr?.baseline?.min || 0).toFixed(4)} · median ${Number(result.dcr?.baseline?.median || 0).toFixed(4)}`;
  aucValue.textContent = Number(result.membership_inference?.attack_auc || 0).toFixed(2);
  privacyExplanation.textContent = result.membership_inference?.interpretation || 'No interpretation available.';

  recommendationList.innerHTML = '';
  (result.recommendations || []).forEach((text) => {
    const item = document.createElement('li');
    item.textContent = text;
    recommendationList.appendChild(item);
  });

  reasonList.innerHTML = '';
  (result.reasons || []).forEach((text) => {
    const item = document.createElement('li');
    item.textContent = text;
    reasonList.appendChild(item);
  });

  renderHistogram(result);
}

privacyRunBtn.addEventListener('click', async () => {
  if (privacyRunInProgress) return;
  const syntheticId = privacySyntheticSelect.value;

  if (!syntheticId) {
    privacyRunMessage.textContent = 'Choose a DP synthetic dataset first.';
    showToast('Choose a DP synthetic dataset first.', 'error');
    return;
  }

  privacyRunInProgress = true;
  privacyRunBtn.disabled = true;
  privacyRunBtn.textContent = 'Checking…';
  privacyRunMessage.textContent = 'Comparing the selected synthetic output with its cleaned source…';
  try {
    const jobPayload = await apiFetch('/api/privacy/', {
      method: 'POST',
      body: JSON.stringify({ synthetic_id: syntheticId }),
    });
    const response = await apiFetch(`/api/jobs/${jobPayload.job_id}/`, { method: 'GET' });
    const result = response.job?.result || response.result;
    if (!result) throw new Error('Privacy check finished without a result.');

    renderReport(result);
    privacyComparedDatasets.textContent = `${jobPayload.synthetic.name} vs ${jobPayload.source.name}`;
    exportReportBtn.dataset.content = JSON.stringify({
      ...result, source: jobPayload.source, synthetic: jobPayload.synthetic, job_id: jobPayload.job_id,
    }, null, 2);
    exportReportBtn.disabled = false;
    privacyRunMessage.textContent = 'Privacy check completed against the linked cleaned source.';
    showToast('Privacy check completed.', 'success');
  } catch (error) {
    privacyRunMessage.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    privacyRunInProgress = false;
    privacyRunBtn.disabled = false;
    privacyRunBtn.textContent = 'Run privacy check';
  }
});

exportReportBtn.addEventListener('click', () => {
  const content = exportReportBtn.dataset.content || '{}';
  const blob = new Blob([content], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'synthlab-privacy-report.json';
  anchor.click();
  URL.revokeObjectURL(url);
});

privacySyntheticSelect.addEventListener('change', () => {
  if (privacySyntheticSelect.value) privacyRunMessage.textContent = 'Ready to compare with the linked cleaned source.';
});

loadPrivacyOptions().catch((error) => {
  privacyRunMessage.textContent = error.message;
  privacySyntheticSelect.innerHTML = '<option value="">Could not load DP datasets</option>';
});
