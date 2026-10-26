# SynthLab

SynthLab is a Django-based synthetic data workbench for building, cleaning, evaluating, and protecting tabular datasets with a student-level differential privacy workflow. The project is designed around a practical research-and-operations flow: generate or upload data, clean it, define a privacy unit, choose a DP budget, generate synthetic data, validate it, and then evaluate downstream utility and model performance.

This system is intentionally built around the idea that privacy should be defined by the real unit of interest: a student, not an individual row. In academic or institutional settings, a student may contribute multiple rows across courses, attendance, assignment, and exam records. The DP guarantee therefore operates over changes to a student’s whole contribution bundle, not just one row.

For container deployment, see [DEPLOYMENT.md](DEPLOYMENT.md).

---

## 1. What the system does

The app supports a full synthetic data pipeline with these stages:

1. Simulate data or upload a real CSV
2. Profile and clean the dataset
3. Define the privacy unit and public bounds
4. Set privacy budget and DP parameters
5. Generate synthetic data under the configured DP policy
6. Validate fidelity and privacy risk
7. Run privacy-utility sweeps
8. Train an analytics model on synthetic data
9. Evaluate against a real holdout split by student
10. Produce academic insights and exportable reports

The UI is structured as a step-by-step pipeline in the sidebar and follows the order above.

---

## 2. High-level architecture

### Django app structure

The project is split into a Django backend and a lab application:

- [backend/config](backend/config) contains Django settings, URLs, ASGI/WSGI bootstrap files.
- [backend/lab](backend/lab) contains the main application logic.
- [backend/lab/models.py](backend/lab/models.py) defines persisted dataset and privacy metadata.
- [backend/lab/views.py](backend/lab/views.py) handles page rendering and JSON API endpoints.
- [backend/lab/urls.py](backend/lab/urls.py) exposes the routes for each pipeline step.
- [backend/lab/templates/lab](backend/lab/templates/lab) contains the HTML pages for the workflow.
- [backend/lab/static/lab/js](backend/lab/static/lab/js) contains the front-end behavior.
- [backend/lab/services](backend/lab/services) contains the logic for generation, cleaning, privacy analysis, and DP accounting.

### Core data model

The app persists datasets and their privacy metadata in the database:

- Dataset
  - Stores a dataset artifact and its file upload.
  - Keeps stage metadata such as simulated, raw, cleaned, synthetic.
- PrivacyPolicy
  - Stores the student-level DP configuration.
  - Contains epsilon, delta, privacy_unit, student_id_col, max_rows_per_student, public_bounds, and accountant configuration.
- BudgetLedger
  - Tracks DP budget consumption across actions.
  - Enforces a budget cap so the system does not exceed the configured spending limit.

The privacy metadata is defined in [backend/lab/models.py](backend/lab/models.py).

---

## 3. End-to-end workflow

### Step 1: Simulate data

The simulator generates synthetic tabular data from a schema. Supported columns include:

- names, emails, phone numbers, addresses, cities, countries
- company, job, dates, datetimes, UUIDs, text
- integer, float, categorical, and boolean fields

The simulator also supports an academic preset with multi-row student records and realistic correlations between attendance, assignments, exams, GPA, and grade outcomes.

Key file:
- [backend/lab/services/simulator.py](backend/lab/services/simulator.py)

Important behavior:
- If the schema includes a student_id column and rows_per_student > 1, the simulator generates repeated rows for the same student.
- This is the foundation of the student-level privacy model.

### Step 2: Upload and clean data

Users can upload a CSV or generate a synthetic dataset and then clean it. Cleaning does several things:

- detect and profile columns
- standardize values
- parse dates
- handle missing values with configurable policies
- drop duplicate rows
- drop identifier columns where appropriate
- apply numeric outlier handling

Key file:
- [backend/lab/services/cleaner.py](backend/lab/services/cleaner.py)

This step is responsible for preparing the dataset so that the privacy unit is preserved correctly. If the user explicitly marks a privacy unit column such as student_id, it is kept instead of being deleted as a generic identifier.

### Step 3: Define the privacy unit

The privacy-definition phase defines:

- the privacy unit (for example, a student)
- student_id column
- max rows per student
- quasi-identifiers
- sensitive attributes
- public bounds

This is critical because the DP guarantee is defined around student-level contribution, not row-level contribution.

The file [backend/lab/views.py](backend/lab/views.py) renders the page and the privacy metadata is represented in the models.

### Step 4: Configure the privacy budget

During the privacy-budget stage, the system saves the DP synthesis budget:

- epsilon
- delta
- PAC-Synth DP marginal combination length (1–3)

Each generator run spends the configured epsilon once. The `BudgetLedger` prevents repeated releases from exceeding that per-dataset cap.

This is important because DP training is not “free”: every training action consumes privacy budget. BudgetLedger enforces a cap so that a requested operation cannot exceed the configured DP allowance.

### Step 5: Generate synthetic data under DP

The generator uses [PAC-Synth's differentially private aggregate-seeded synthesizer](https://pypi.org/project/pac-synth/). Each student is first reduced to one bounded record, the student ID is excluded, numeric features are clipped to public bounds and binned, and the library computes DP marginals before sampling synthetic rows.

Key implementation files:
- [backend/lab/services/dp_generator.py](backend/lab/services/dp_generator.py)
- [backend/lab/views.py](backend/lab/views.py)
- [backend/lab/models.py](backend/lab/models.py)

The project keeps a separation between:

- standard non-private synthetic generation
- differential private generation workflows

This allows the app to support both legacy baselines and privacy-aware generation paths.

Key baseline generation-related file:
- [backend/lab/services/generator.py](backend/lab/services/generator.py)

### Step 6: Validate the outputs

Once synthetic data is generated, the app evaluates it with a validation pipeline that checks:

- fidelity to the original data
- risk of re-identification
- membership inference signals
- empirical privacy diagnostics

Key file:
- [backend/lab/services/privacy.py](backend/lab/services/privacy.py)

These checks are useful diagnostics but they are not a substitute for formal DP guarantees. They help interpret the quality and sensitivity of the synthetic output.

### Step 7: Privacy-utility sweep

The app also supports a privacy-utility evaluation loop, where the same data is evaluated under several epsilon settings to understand the trade-off between stronger privacy and weaker utility.

This phase helps answer:

- How much utility is lost when epsilon is reduced?
- Which budget level achieves the best practical result?
- Does the model remain useful while keeping the DP guarantee strong?

### Step 8: Train an analytics model

The system can train downstream models on the generated synthetic data and compare them against real data or a real holdout split. The aim is not only to generate synthetic records, but to use them to support real analytics while preserving privacy.

This is where the project connects the synthetic generation workflow to actual model evaluation.

### Step 9: Produce insights

The final step summarizes patterns from the synthetic data while clearly labeling the guarantee:

- privacy unit: student
- epsilon and delta
- privacy-preserving report wording

The app is designed to avoid claiming that the data is simply anonymous. It instead reports the actual formal statement: synthetic data is generated under a student-level DP policy with a certain epsilon and delta.

---

## 4. How the privacy model works

Unlike a row-level DP system, this project treats each student as the protected unit. That means:

- one student may contribute several rows
- the dataset still remains coherent across all a student’s records
- train/test separation must preserve student membership
- DP accounting must reflect the student-level contribution bound

This is the key design decision of the project.

In practical terms, the workflow expects that:

- each data record is associated with a student_id
- repeated rows per student are allowed and expected
- the privacy unit is defined before training or generation
- group-level splits and public bounds are honored

This is why the simulator includes academic presets with repeated rows and the cleaner explicitly handles a privacy_unit_key instead of dropping it automatically.

### How to read the guarantee

A statement like:

- “Differentially private with epsilon = 3.0, delta = 1e-5 at the student level”

means the DP guarantee applies to the effect of changing one student’s entire contribution bundle. It does not mean one row is protected in isolation.

This is a stronger, more realistic interpretation for academic data than a naive row-level guarantee.

---

## 5. Files that matter most

### Backend entry points

- [backend/manage.py](backend/manage.py)
- [backend/config/settings.py](backend/config/settings.py)
- [backend/config/urls.py](backend/config/urls.py)

### Application logic

- [backend/lab/views.py](backend/lab/views.py)
- [backend/lab/models.py](backend/lab/models.py)
- [backend/lab/urls.py](backend/lab/urls.py)

### Services

- [backend/lab/services/simulator.py](backend/lab/services/simulator.py)
- [backend/lab/services/cleaner.py](backend/lab/services/cleaner.py)
- [backend/lab/services/privacy.py](backend/lab/services/privacy.py)
- [backend/lab/services/generator.py](backend/lab/services/generator.py)
- [backend/lab/services/dp_accounting.py](backend/lab/services/dp_accounting.py)
- [backend/lab/services/privacy_definition.py](backend/lab/services/privacy_definition.py)

### UI

- [backend/lab/templates/lab](backend/lab/templates/lab)
- [backend/lab/static/lab/js](backend/lab/static/lab/js)
- [backend/lab/static/lab/css/style.css](backend/lab/static/lab/css/style.css)

---

## 6. Running the project

From the project root:

```bash
cd backend
./synthlab/bin/python manage.py migrate
./synthlab/bin/python manage.py runserver
```

Then open the app in the browser at:

```text
http://127.0.0.1:8000/
```

### Run tests

```bash
cd backend
./synthlab/bin/python manage.py test lab
```

---

## 7. Data flow in one sentence

The app takes a dataset, turns it into a cleaned and student-aware table, defines a privacy policy for students, spends a DP budget during generation or training, validates the output, and then uses the result for downstream analytics with a clear, honest privacy statement.

---

## 8. Important design notes

- The project is intentionally student-centric, not row-centric.
- Public bounds are treated as assumptions that must be declared by the user or the institutional context.
- Empirical checks such as membership inference or DCR are useful support metrics, not proof of privacy.
- The app keeps a clear separation between the non-private baseline pipeline and the differentially private path.
- Synthetic data is meant to support downstream tasks while preserving privacy, not to provide a guarantee of anonymity by itself.

---

## 9. Typical use case

A realistic flow might be:

1. Simulate academic records with student_id, GPA, attendance, final_grade, assignment totals.
2. Clean the dataset and mark student_id as the privacy unit.
3. Set student-level DP settings with epsilon = 3 and delta = 1e-5.
4. Generate synthetic academic records under those settings.
5. Validate the synthetic data for fidelity and risk.
6. Train a model that predicts pass/fail or identifies at-risk students.
7. Produce an insight report that states the privacy guarantee clearly.

This matches the project’s design and the course of the workflow implemented in the app.
