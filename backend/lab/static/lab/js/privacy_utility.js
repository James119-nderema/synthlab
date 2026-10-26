const sweepDatasetSelect = document.getElementById('sweepDatasetSelect');
const sweepTargetSelect = document.getElementById('sweepTargetSelect');
const sweepEpsilonsInput = document.getElementById('sweepEpsilonsInput');
const runSweepBtn = document.getElementById('runSweepBtn');
const sweepBudgetStatus = document.getElementById('sweepBudgetStatus');
const sweepStatus = document.getElementById('sweepStatus');
const sweepTableBody = document.getElementById('sweepTableBody');
const sweepDatasets = new Map();
let sweepRunning = false;

async function loadSweepDatasets() {
  const response = await apiFetch('/api/datasets/?stage=synthetic&dp=true', { method: 'GET' });
  const datasets = (response.datasets || []).filter((dataset) => dataset.source_dataset_id);
  sweepDatasetSelect.innerHTML = '<option value="">Choose a DP synthetic dataset</option>';
  datasets.forEach((dataset) => {
    sweepDatasets.set(dataset.id, dataset);
    const option = document.createElement('option');
    option.value = dataset.id;
    option.textContent = `${dataset.name} · source: ${dataset.source_dataset_name}`;
    sweepDatasetSelect.appendChild(option);
  });
  if (!datasets.length) {
    sweepBudgetStatus.textContent = 'No DP synthetic outputs with linked cleaned sources are available. Train the DP generator first.';
  }
}

async function loadSweepConfiguration() {
  const dataset = sweepDatasets.get(sweepDatasetSelect.value);
  sweepTargetSelect.innerHTML = '<option value="">Loading numeric targets…</option>';
  sweepTargetSelect.disabled = true;
  sweepBudgetStatus.textContent = '';
  sweepStatus.textContent = '';
  if (!dataset) return;

  const [budget, profile] = await Promise.all([
    apiFetch(`/api/privacy-utility/options/?synthetic_id=${encodeURIComponent(dataset.id)}`, { method: 'GET' }),
    apiFetch(`/api/datasets/${dataset.source_dataset_id}/profile/`, { method: 'GET' }),
  ]);
  const epsilonRemaining = Number(budget.epsilon_remaining);
  const deltaRemaining = Number(budget.delta_remaining);
  sweepBudgetStatus.textContent = `Source: ${budget.source.name}. Remaining budget: ε=${epsilonRemaining.toPrecision(4)} and δ=${deltaRemaining.toExponential(2)}. This sweep spends the sum of the entered epsilon values and the remaining delta budget.`;

  sweepTargetSelect.innerHTML = '<option value="">Choose a numeric prediction target</option>';
  const targets = Object.entries(profile.profile?.columns || {})
    .filter(([, column]) => /^(int|float)/i.test(column.dtype) && !column.is_identifier)
    .map(([name]) => name);
  targets.forEach((target) => {
    const option = document.createElement('option');
    option.value = target;
    option.textContent = target;
    sweepTargetSelect.appendChild(option);
  });
  if (targets.includes('gpa')) sweepTargetSelect.value = 'gpa';
  else if (targets.length) sweepTargetSelect.value = targets[0];
  sweepTargetSelect.disabled = !targets.length;

  const suggested = (budget.suggested_epsilons || []).filter((value) => Number(value) > 0);
  sweepEpsilonsInput.value = suggested.length >= 2 ? suggested.join(', ') : '';
  if (epsilonRemaining <= 0 || deltaRemaining <= 0) {
    sweepStatus.textContent = 'This source has no remaining privacy budget for a sweep. Increase the configured epsilon and delta limits, then return here.';
  } else if (suggested.length < 2) {
    sweepStatus.textContent = 'At least two distinct positive epsilon values are needed. Increase the remaining epsilon budget or enter two values whose total is within the remaining budget.';
  } else {
    sweepStatus.textContent = 'The suggested epsilon values use the remaining epsilon budget. Edit them if needed; their sum must stay within the displayed amount.';
  }
}

function clearSweepResults(message) {
  document.getElementById('recommendedEpsilon').textContent = '—';
  document.getElementById('bestUtility').textContent = '—';
  document.getElementById('recommendedMia').textContent = '—';
  sweepTableBody.innerHTML = `<tr><td colspan="5">${message}</td></tr>`;
}

sweepDatasetSelect.addEventListener('change', () => {
  clearSweepResults('Choose a dataset and run the sweep.');
  loadSweepConfiguration().catch((error) => { sweepStatus.textContent = error.message; });
});

runSweepBtn.addEventListener('click', async () => {
  if (sweepRunning) return;
  const syntheticId = sweepDatasetSelect.value;
  const target = sweepTargetSelect.value;
  const epsilonText = sweepEpsilonsInput.value.trim();
  const epsilons = epsilonText.split(',').map((value) => Number(value.trim()));
  if (!syntheticId || !target || !epsilonText || epsilons.some((value) => !Number.isFinite(value) || value <= 0)) {
    sweepStatus.textContent = 'Choose a dataset and numeric target, then enter valid positive epsilon values.';
    showToast('Complete the dataset, target, and epsilon values first.', 'error');
    return;
  }

  sweepRunning = true;
  runSweepBtn.disabled = true;
  runSweepBtn.textContent = 'Running sweep…';
  sweepStatus.textContent = 'Training one DP generator per epsilon and measuring privacy and utility. This can take a while.';
  try {
    const response = await apiFetch('/api/privacy-utility/sweep/', {
      method: 'POST',
      body: JSON.stringify({ synthetic_id: syntheticId, target, epsilons }),
    });
    const results = response.results || [];
    sweepTableBody.innerHTML = '';
    results.forEach((result) => {
      const row = document.createElement('tr');
      const values = [
        Number(result.epsilon).toPrecision(4),
        Number(result.utility_score).toFixed(3),
        result.tstr_r2 == null ? 'Not defined' : Number(result.tstr_r2).toFixed(3),
        Number(result.mia_auc).toFixed(3),
        result.verdict,
      ];
      values.forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      });
      sweepTableBody.appendChild(row);
    });

    const recommended = results.find((row) => Number(row.epsilon) === Number(response.recommended_epsilon));
    document.getElementById('recommendedEpsilon').textContent = Number(response.recommended_epsilon).toPrecision(4);
    document.getElementById('bestUtility').textContent = recommended
      ? `${Number(recommended.utility_score).toFixed(3)} (Δ ${Number(recommended.utility_vs_baseline).toFixed(3)} vs split baseline)`
      : '—';
    document.getElementById('recommendedMia').textContent = recommended ? Number(recommended.mia_auc).toFixed(3) : '—';
    const allMissingFeatures = [...new Set(results.flatMap((result) =>
      result.tstr_diagnostics?.all_missing_features || []))];
    const insufficientTstrPoints = results.filter((result) =>
      result.tstr_diagnostics?.status === 'insufficient target records for TSTR');
    const missingTrainingValues = results.reduce((total, result) =>
      total + Number(result.tstr_diagnostics?.missing_training_values || 0), 0);
    const tstrDiagnostic = insufficientTstrPoints.length
      ? ` TSTR was unavailable for ${insufficientTstrPoints.length} point(s) because generated ${target} values were too sparse: ${insufficientTstrPoints.map((result) => `ε=${Number(result.epsilon).toPrecision(3)} had ${result.tstr_diagnostics.synthetic_target_records} valid synthetic target rows`).join('; ')}.`
      : allMissingFeatures.length
      ? ` TSTR imputed all-missing feature(s) with 0: ${allMissingFeatures.join(', ')}. ${missingTrainingValues} missing feature values were imputed across the sweep.`
      : missingTrainingValues
        ? ` TSTR imputed ${missingTrainingValues} missing feature values across the sweep; no feature was entirely missing.`
        : ' TSTR found no missing training feature values.';
    const generatedRows = [...new Set(results.map((result) => Number(result.generated_rows)))];
    const generationSize = generatedRows.length === 1 ? `${generatedRows[0]} rows per point` : `${generatedRows.join(', ')} generated rows across points`;
    const completionMessage = `Sweep completed for ${response.synthetic.name} against ${response.source.name}. Used ${response.source_rows} source rows and ${response.reference_rows} rows from the selected DP file (${response.reference_valid_target_rows} valid ${target} values); generated ${generationSize}. Spent ε=${Number(response.epsilon_spent).toPrecision(4)} and δ=${Number(response.delta_spent).toExponential(2)} in total. ${response.recommendation_note}${tstrDiagnostic}`;
    sweepStatus.textContent = completionMessage;
    showToast('Privacy–utility sweep completed.', 'success');
    await loadSweepConfiguration();
    sweepStatus.textContent = completionMessage;
  } catch (error) {
    sweepStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    sweepRunning = false;
    runSweepBtn.disabled = false;
    runSweepBtn.textContent = 'Run privacy–utility sweep';
  }
});

loadSweepDatasets().catch((error) => {
  sweepBudgetStatus.textContent = error.message;
  sweepDatasetSelect.innerHTML = '<option value="">Could not load DP datasets</option>';
});
