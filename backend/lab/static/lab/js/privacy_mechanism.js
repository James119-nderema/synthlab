const privacyBudgetForm = document.getElementById('privacyBudgetForm');
const budgetDatasetSelect = document.getElementById('budgetDatasetSelect');
const budgetStatus = document.getElementById('budgetStatus');
const deltaLimitHint = document.getElementById('deltaLimitHint');

async function loadBudgetDatasets() {
  try {
    const payload = await apiFetch('/api/datasets/?stage=cleaned', { method: 'GET' });
    budgetDatasetSelect.innerHTML = '';
    const prompt = document.createElement('option'); prompt.value = ''; prompt.textContent = 'Choose a cleaned dataset'; budgetDatasetSelect.appendChild(prompt);
    (payload.datasets || []).forEach((dataset) => {
      const option = document.createElement('option'); option.value = dataset.id; option.textContent = `${dataset.name} · ${dataset.rows} rows`; budgetDatasetSelect.appendChild(option);
    });
  } catch (error) {
    budgetDatasetSelect.innerHTML = `<option value="">Unable to load datasets: ${error.message}</option>`;
  }
}

privacyBudgetForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = document.getElementById('saveBudgetBtn');
  button.disabled = true;
  budgetStatus.classList.remove('hidden');
  budgetStatus.textContent = 'Saving privacy settings…';
  try {
    await apiFetch('/api/privacy-budget/', {
      method: 'POST',
      body: JSON.stringify({
        dataset_id: budgetDatasetSelect.value,
        epsilon: Number(privacyBudgetForm.elements.epsilon.value),
        delta: Number(privacyBudgetForm.elements.delta.value),
        reporting_length: Number(privacyBudgetForm.elements.reporting_length.value),
      }),
    });
    budgetStatus.textContent = 'Privacy settings saved for this cleaned dataset.';
    showToast('Privacy settings saved.', 'success');
  } catch (error) {
    budgetStatus.textContent = error.message;
    showToast(error.message, 'error');
  } finally {
    button.disabled = false;
  }
});

budgetDatasetSelect.addEventListener('change', async () => {
  if (!budgetDatasetSelect.value) {
    deltaLimitHint.textContent = 'Must be less than 1 / number of students in the cleaned dataset.';
    return;
  }
  try {
    const profile = await apiFetch(`/api/datasets/${budgetDatasetSelect.value}/profile/`, { method: 'GET' });
    const students = Number(profile.students || 0);
    deltaLimitHint.textContent = students
      ? `This dataset has ${students} students. Delta must be less than 1 / ${students} (${(1 / students).toPrecision(4)}).`
      : 'A student ID column is required to calculate the valid delta limit.';
  } catch (error) {
    deltaLimitHint.textContent = error.message;
  }
});

loadBudgetDatasets();
