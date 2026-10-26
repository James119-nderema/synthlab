const TYPE_CONFIG = {
  name: ['max_chars'],
  email: [],
  phone: [],
  address: [],
  city: [],
  country: [],
  company: [],
  job: [],
  date: [],
  datetime: [],
  uuid: [],
  text: ['max_chars'],
  integer: ['min', 'max'],
  float: ['distribution', 'mean', 'std', 'min', 'max'],
  categorical: [],
  boolean: ['probability'],
};

const exampleSchemaSelect = document.getElementById('exampleSchemaSelect');

const exampleSchemas = {
  customer: [
    { name: 'customer_id', type: 'uuid', params: {} },
    { name: 'age', type: 'integer', params: { min: 18, max: 75 } },
    { name: 'income', type: 'float', params: { distribution: 'normal', mean: 65000, std: 18000, min: 15000, max: 200000 } },
    { name: 'city', type: 'city', params: {} },
    { name: 'gender', type: 'categorical', params: { values: ['Female', 'Male', 'Non-binary'], weights: [0.48, 0.48, 0.04] } },
    { name: 'signup_date', type: 'date', params: {} },
    { name: 'is_premium', type: 'boolean', params: { probability: 0.2 } },
  ],
  school: [
    { name: 'student_id', type: 'uuid', params: {} },
    { name: 'school_name', type: 'categorical', params: { values: ['Greenwood Academy', 'Nairobi High', 'St. Marys College', 'Kisumu Technical', 'Mombasa Secondary', 'Lakeview Academy'], weights: [0.18, 0.22, 0.16, 0.2, 0.14, 0.1] } },
    { name: 'university', type: 'categorical', params: { values: ['University of Nairobi', 'Kenyatta University', 'Strathmore', 'Maseno', 'Egerton', 'Moi University'], weights: [0.22, 0.2, 0.16, 0.18, 0.14, 0.1] } },
    { name: 'county', type: 'categorical', params: { values: ['Nairobi', 'Kiambu', 'Kisumu', 'Nakuru', 'Mombasa', 'Kisii'], weights: [0.26, 0.18, 0.15, 0.17, 0.12, 0.12] } },
    { name: 'tribe', type: 'categorical', params: { values: ['Kikuyu', 'Luhya', 'Kalenjin', 'Kisii', 'Luo', 'Kamba'], weights: [0.24, 0.18, 0.17, 0.13, 0.16, 0.12] } },
    { name: 'math_score', type: 'integer', params: { min: 35, max: 100 } },
    { name: 'science_score', type: 'integer', params: { min: 40, max: 100 } },
    { name: 'attendance_rate', type: 'float', params: { distribution: 'normal', mean: 88, std: 8, min: 50, max: 100 } },
    { name: 'fee_balance', type: 'float', params: { distribution: 'normal', mean: 15000, std: 8000, min: 0, max: 50000 } },
  ],
  academic: [
    { name: 'student_id', type: 'uuid', params: {} },
    { name: 'gender', type: 'categorical', params: { values: ['Female', 'Male', 'Non-binary'], weights: [0.52, 0.45, 0.03] } },
    { name: 'age', type: 'integer', params: { min: 17, max: 35 } },
    { name: 'department', type: 'categorical', params: { values: ['Computer Science', 'Mathematics', 'Biology', 'Economics', 'Psychology'], weights: [0.28, 0.22, 0.18, 0.16, 0.16] } },
    { name: 'year_of_study', type: 'integer', params: { min: 1, max: 4 } },
    { name: 'course_code', type: 'categorical', params: { values: ['CS101', 'CS201', 'MATH120', 'BIO210', 'ECON110', 'PSY101', 'CS310', 'ENG200'], weights: [0.18, 0.15, 0.14, 0.12, 0.14, 0.1, 0.1, 0.07] } },
    { name: 'attendance_pct', type: 'float', params: { distribution: 'normal', mean: 82, std: 12, min: 40, max: 100 } },
    { name: 'study_hours_week', type: 'float', params: { distribution: 'normal', mean: 9, std: 3.5, min: 1, max: 30 } },
    { name: 'assignment_avg', type: 'float', params: { distribution: 'normal', mean: 74, std: 15, min: 0, max: 100 } },
    { name: 'midterm', type: 'float', params: { distribution: 'normal', mean: 72, std: 18, min: 0, max: 100 } },
    { name: 'final_exam', type: 'float', params: { distribution: 'normal', mean: 77, std: 16, min: 0, max: 100 } },
    { name: 'gpa', type: 'float', params: { distribution: 'normal', mean: 3.1, std: 0.6, min: 0, max: 4 } },
    { name: 'scholarship', type: 'boolean', params: { probability: 0.22 } },
    { name: 'final_grade', type: 'categorical', params: { values: ['A', 'B', 'C', 'D', 'F'], weights: [0.22, 0.28, 0.24, 0.15, 0.11] } },
    { name: 'pass_fail', type: 'boolean', params: { probability: 0.78 } },
  ],
  jobs: [
    { name: 'employee_id', type: 'uuid', params: {} },
    { name: 'job_title', type: 'categorical', params: { values: ['Software Engineer', 'Data Analyst', 'Nurse', 'Teacher', 'Accountant', 'Project Manager', 'Sales Executive'], weights: [0.18, 0.16, 0.14, 0.14, 0.13, 0.12, 0.13] } },
    { name: 'industry', type: 'categorical', params: { values: ['Technology', 'Healthcare', 'Education', 'Finance', 'Retail', 'Manufacturing'], weights: [0.25, 0.2, 0.18, 0.15, 0.12, 0.1] } },
    { name: 'country', type: 'country', params: {} },
    { name: 'years_experience', type: 'integer', params: { min: 0, max: 25 } },
    { name: 'salary', type: 'float', params: { distribution: 'normal', mean: 75000, std: 30000, min: 20000, max: 200000 } },
    { name: 'remote_ratio', type: 'float', params: { distribution: 'uniform', min: 0, max: 100 } },
    { name: 'employment_status', type: 'categorical', params: { values: ['Full-time', 'Part-time', 'Contract', 'Intern'], weights: [0.55, 0.2, 0.18, 0.07] } },
  ],
  business: [
    { name: 'business_id', type: 'uuid', params: {} },
    { name: 'business_name', type: 'company', params: {} },
    { name: 'industry', type: 'categorical', params: { values: ['Retail', 'Logistics', 'Hospitality', 'Agriculture', 'Manufacturing', 'Technology'], weights: [0.18, 0.16, 0.14, 0.17, 0.15, 0.2] } },
    { name: 'city', type: 'city', params: {} },
    { name: 'revenue', type: 'float', params: { distribution: 'lognormal', mean: 11.5, std: 0.8, min: 1000, max: 2000000 } },
    { name: 'employees', type: 'integer', params: { min: 5, max: 500 } },
    { name: 'profit_margin', type: 'float', params: { distribution: 'normal', mean: 18, std: 8, min: -10, max: 60 } },
    { name: 'is_profitable', type: 'boolean', params: { probability: 0.7 } },
  ],
};

const schemaRowsEl = document.getElementById('schemaRows');
const rowCountInput = document.getElementById('rowCountInput');
const rowsPerStudentInput = document.getElementById('rowsPerStudentInput');
const seedInput = document.getElementById('seedInput');
const previewBtn = document.getElementById('previewBtn');
const generateBtn = document.getElementById('generateBtn');
const loadExampleBtn = document.getElementById('loadExampleBtn');
const addColumnBtn = document.getElementById('addColumnBtn');
const previewStatus = document.getElementById('previewStatus');
const previewHead = document.getElementById('previewHead');
const previewBody = document.getElementById('previewBody');
const summaryCard = document.getElementById('summaryCard');
const summaryRows = document.getElementById('summaryRows');
const summaryCols = document.getElementById('summaryCols');
const summaryDtypes = document.getElementById('summaryDtypes');
const downloadBtn = document.getElementById('downloadBtn');

let generatedDatasetId = null;

function buildParamField(key, value = '') {
  const field = document.createElement('div');
  field.className = 'param-field';

  const label = document.createElement('label');
  label.textContent = key;

  const input = document.createElement('input');
  input.type = 'text';
  input.name = `param_${key}`;
  input.value = value;
  input.placeholder = key;

  label.appendChild(input);
  field.appendChild(label);
  return field;
}

function getSchemaFromRows() {
  const rows = [...schemaRowsEl.querySelectorAll('.schema-row')];
  return rows.map((row) => {
    const nameInput = row.querySelector('.column-name');
    const typeSelect = row.querySelector('.column-type');
    const paramInputs = row.querySelectorAll('.param-field input');

    const params = {};
    paramInputs.forEach((input) => {
      const key = input.name.replace('param_', '');
      if (!input.value.trim()) return;
      if (key === 'values' || key === 'weights') {
        params[key] = input.value.split(',').map((item) => item.trim()).filter(Boolean);
      } else if (['min', 'max', 'mean', 'std', 'probability', 'missing_pct', 'max_chars'].includes(key)) {
        params[key] = Number(input.value);
      } else {
        params[key] = input.value;
      }
    });

    return {
      name: nameInput.value.trim(),
      type: typeSelect.value,
      params,
    };
  }).filter((col) => col.name && col.type);
}

function renderTypeParams(row, type) {
  const paramBlock = row.querySelector('.param-block');
  if (!paramBlock) return;
  const allowedKeys = TYPE_CONFIG[type] || [];

  paramBlock.innerHTML = '';
  allowedKeys.forEach((key) => {
    const field = buildParamField(key, '');
    paramBlock.appendChild(field);
  });

  if (type === 'categorical') {
    const valuesField = buildParamField('values', '');
    const weightsField = buildParamField('weights', '');
    paramBlock.appendChild(valuesField);
    paramBlock.appendChild(weightsField);
  }
}

function addColumn(column = { name: '', type: 'name', params: {} }) {
  const row = document.createElement('tr');
  row.className = 'schema-row';

  const nameCell = document.createElement('td');
  const nameInput = document.createElement('input');
  nameInput.type = 'text';
  nameInput.className = 'column-name';
  nameInput.value = column.name || '';
  nameInput.placeholder = 'column_name';
  nameCell.appendChild(nameInput);

  const typeCell = document.createElement('td');
  const select = document.createElement('select');
  select.className = 'column-type';
  select.innerHTML = `
    <option value="name">name</option>
    <option value="email">email</option>
    <option value="phone">phone</option>
    <option value="address">address</option>
    <option value="city">city</option>
    <option value="country">country</option>
    <option value="company">company</option>
    <option value="job">job</option>
    <option value="date">date</option>
    <option value="datetime">datetime</option>
    <option value="uuid">uuid</option>
    <option value="text">text</option>
    <option value="integer">integer</option>
    <option value="float">float</option>
    <option value="categorical">categorical</option>
    <option value="boolean">boolean</option>
  `;
  select.value = column.type || 'name';
  typeCell.appendChild(select);

  const paramCell = document.createElement('td');
  const paramBlock = document.createElement('div');
  paramBlock.className = 'param-block';
  paramCell.appendChild(paramBlock);

  const removeCell = document.createElement('td');
  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'btn btn-icon remove-row-btn';
  removeBtn.textContent = 'Remove';
  removeBtn.addEventListener('click', () => {
    row.remove();
  });
  removeCell.appendChild(removeBtn);

  row.appendChild(nameCell);
  row.appendChild(typeCell);
  row.appendChild(paramCell);
  row.appendChild(removeCell);
  schemaRowsEl.appendChild(row);

  select.addEventListener('change', () => renderTypeParams(row, select.value));
  renderTypeParams(row, select.value);

  if (column.params) {
    Object.entries(column.params).forEach(([key, value]) => {
      const inputs = row.querySelectorAll(`input[name="param_${key}"]`);
      if (inputs.length > 0) {
        const input = inputs[0];
        input.value = Array.isArray(value) ? value.join(', ') : value;
      }
    });
  }
}

function loadExampleSchema() {
  const presetKey = exampleSchemaSelect?.value || 'customer';
  const preset = exampleSchemas[presetKey] || exampleSchemas.customer;
  schemaRowsEl.innerHTML = '';
  preset.forEach((column) => addColumn(column));
}

function setPreviewStatus(message, variant = 'info') {
  previewStatus.className = `status-inline ${variant}`;
  previewStatus.textContent = message;
}

function renderPreviewTable(rows, columns) {
  previewHead.innerHTML = '';
  previewBody.innerHTML = '';

  const headerRow = document.createElement('tr');
  columns.forEach((column) => {
    const th = document.createElement('th');
    th.textContent = column;
    headerRow.appendChild(th);
  });
  previewHead.appendChild(headerRow);

  rows.forEach((row) => {
    const tr = document.createElement('tr');
    columns.forEach((column) => {
      const td = document.createElement('td');
      const value = row[column];
      td.textContent = value === null || value === undefined ? 'NULL' : String(value);
      tr.appendChild(td);
    });
    previewBody.appendChild(tr);
  });
}

async function runPreview() {
  const payload = {
    schema: getSchemaFromRows(),
    n_rows: Number(rowCountInput.value || 10),
    rows_per_student: Number(rowsPerStudentInput?.value || 1),
    seed: Number(seedInput.value || 0),
  };

  try {
    const result = await apiFetch('/api/simulate/preview/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    renderPreviewTable(result.rows, result.columns || []);
    setPreviewStatus(`Preview ready: ${result.rows.length} rows loaded.`, 'success');
  } catch (error) {
    setPreviewStatus(error.message, 'error');
    console.error(error);
  }
}

async function runGenerate() {
  const payload = {
    schema: getSchemaFromRows(),
    n_rows: Number(rowCountInput.value || 10),
    rows_per_student: Number(rowsPerStudentInput?.value || 1),
    seed: Number(seedInput.value || 0),
  };

  const button = generateBtn;
  setLoading(button, true, 'Generating...');

  try {
    const result = await apiFetch('/api/simulate/generate/', {
      method: 'POST',
      body: JSON.stringify(payload),
    });

    generatedDatasetId = result.dataset_id;
    summaryRows.textContent = result.rows;
    summaryCols.textContent = result.columns;
    summaryDtypes.innerHTML = '';
    (result.dtypes || []).forEach((dtype) => {
      const badge = document.createElement('span');
      badge.className = 'pill';
      badge.textContent = dtype;
      summaryDtypes.appendChild(badge);
    });

    downloadBtn.href = `/api/datasets/${result.dataset_id}/download/`;
    summaryCard.classList.remove('hidden');
    setPreviewStatus('Dataset generated successfully.', 'success');
    showToast('Simulation generated successfully.', 'success');
  } catch (error) {
    setPreviewStatus(error.message, 'error');
    showToast(error.message, 'error');
  } finally {
    setLoading(button, false);
  }
}

addColumnBtn.addEventListener('click', () => addColumn());
previewBtn.addEventListener('click', runPreview);
generateBtn.addEventListener('click', runGenerate);
loadExampleBtn.addEventListener('click', loadExampleSchema);

addColumn();
loadExampleSchema();
