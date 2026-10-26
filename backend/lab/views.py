import json
import math
import copy
from pathlib import Path
from uuid import UUID

import pandas as pd
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import BudgetLedger, Dataset, PrivacyPolicy
from .services.cleaner import clean, profile
from .services.generator import evaluate_fidelity
from .services.privacy import run_privacy_check
from .services.privacy_definition import DEFAULT_PUBLIC_BOUNDS, public_bounds_for_columns, risk_scan
from .services.dp_generator import generate_dp_synthetic
from .services.simulator import simulate
from .services.utility import evaluate_utility

_JOB_STORE: dict[str, dict[str, object]] = {}


def _build_steps(current: str = "prepare") -> list[dict[str, object]]:
    steps = [
        ("real_data", "Real Academic Data", "/real-data/"),
        ("prepare", "Data Preprocessing", "/data-preprocessing/"),
        ("privacy_definition", "Define Student-Level Privacy", "/student-privacy/"),
        ("privacy_budget", "Configure Privacy Mechanism", "/privacy-mechanism/"),
        ("generate_dp", "Train Synthetic Data Generator with Differential Privacy", "/dp-generator/"),
        ("generate_records", "Generate Synthetic Records", "/synthetic-records/"),
        ("validate", "Validate Synthetic Data", "/synthetic-validation/"),
        ("privacy_eval", "Privacy Evaluation", "/privacy-evaluation/"),
        ("utility_eval", "Utility Evaluation", "/utility-evaluation/"),
        ("privacy_utility", "Privacy–Utility Analysis", "/privacy-utility-analysis/"),
        ("model", "Train AI Analytics Model", "/ai-analytics-model/"),
        ("predictions", "Evaluate Predictions", "/evaluate-predictions/"),
        ("insights", "Privacy-Preserving Academic Insights", "/academic-insights/"),
    ]
    current_index = next((index for index, (slug, _, _) in enumerate(steps) if slug == current), 0)
    return [
        {
            "number": index,
            "label": label,
            "url": url,
            "current": slug == current,
            "done": index - 1 < current_index,
        }
        for index, (slug, label, url) in enumerate(steps, start=1)
    ]


def index(request):
    return redirect("real_data")


def legacy_page(request, target):
    return redirect(target)


def real_data_page(request):
    return render(request, "lab/real_data.html", {"steps": _build_steps("real_data")})


def data_preprocessing_page(request):
    source_datasets = Dataset.objects.filter(
        stage__in=[Dataset.STAGE_RAW, Dataset.STAGE_SIMULATED],
    ).exclude(file="").order_by("-created_at")
    return render(request, "lab/data_preprocessing.html", {
        "steps": _build_steps("prepare"),
        "source_datasets": source_datasets,
    })


def student_privacy_page(request):
    return render(request, "lab/student_privacy.html", {"steps": _build_steps("privacy_definition")})


def privacy_mechanism_page(request):
    return render(request, "lab/privacy_mechanism.html", {"steps": _build_steps("privacy_budget")})


def dp_generator_page(request):
    return render(request, "lab/dp_generator.html", {"steps": _build_steps("generate_dp")})


def synthetic_records_page(request):
    return render(request, "lab/synthetic_records.html", {"steps": _build_steps("generate_records")})


@ensure_csrf_cookie
def synthetic_validation_page(request):
    return render(request, "lab/synthetic_validation.html", {"steps": _build_steps("validate")})


@ensure_csrf_cookie
def privacy_evaluation_page(request):
    return render(request, "lab/privacy_evaluation.html", {"steps": _build_steps("privacy_eval")})


@ensure_csrf_cookie
def utility_evaluation_page(request):
    return render(request, "lab/utility_evaluation.html", {"steps": _build_steps("utility_eval")})


@ensure_csrf_cookie
def privacy_utility_analysis_page(request):
    return render(request, "lab/privacy_utility_analysis.html", {"steps": _build_steps("privacy_utility")})


def ai_analytics_model_page(request):
    return render(request, "lab/ai_analytics_model.html", {"steps": _build_steps("model")})


def evaluate_predictions_page(request):
    return render(request, "lab/evaluate_predictions.html", {"steps": _build_steps("predictions")})


def academic_insights_page(request):
    return render(request, "lab/academic_insights.html", {"steps": _build_steps("insights")})


@require_http_methods(["GET", "POST"])
def academic_insights_api(request):
    if request.method == "GET":
        try:
            synthetic_id = UUID(str(request.GET.get("synthetic_id")))
            dataset = Dataset.objects.get(id=synthetic_id, stage=Dataset.STAGE_SYNTHETIC, differentially_private=True)
        except (TypeError, ValueError, Dataset.DoesNotExist):
            return JsonResponse({"ok": False, "error": "Choose a valid DP synthetic dataset."}, status=404)
        source = _get_validation_source(dataset)
        if source is None:
            return JsonResponse({"ok": False, "error": "The DP output has no linked cleaned source."}, status=400)
        try:
            dataframe = pd.read_csv(dataset.file.path, nrows=1000)
            policy = PrivacyPolicy.objects.filter(dataset=source).first()
        except (OSError, ValueError) as exc:
            return JsonResponse({"ok": False, "error": f"Unable to read the DP dataset: {exc}"}, status=400)
        numeric = [name for name in dataframe.columns if pd.api.types.is_numeric_dtype(dataframe[name])
                   and name != (policy.student_id_col if policy else "student_id")]
        categorical = [name for name in dataframe.columns if not pd.api.types.is_numeric_dtype(dataframe[name])
                       and name != (policy.student_id_col if policy else "student_id")]
        ledger = list(BudgetLedger.objects.filter(dataset=source))
        return JsonResponse({"ok": True, "dataset": {"id": str(dataset.id), "name": dataset.name,
                                                         "rows": dataset.rows, "source": source.name},
                             "numeric_columns": numeric, "categorical_columns": categorical,
                             "privacy": {"epsilon": float(policy.epsilon) if policy else None,
                                         "delta": float(policy.delta) if policy else None,
                                         "epsilon_spent": sum(item.epsilon_spent for item in ledger),
                                         "delta_spent": sum(item.delta for item in ledger),
                                         "accountant": policy.get_accountant_display() if policy else "Unavailable"}})

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        synthetic_id = UUID(str(payload.get("synthetic_id")))
        group_column = str(payload.get("group_column") or "").strip()
        metric_column = str(payload.get("metric_column") or "").strip()
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Choose a dataset, grouping column, and numeric measure."}, status=400)
    try:
        dataset = Dataset.objects.get(id=synthetic_id, stage=Dataset.STAGE_SYNTHETIC, differentially_private=True)
    except Dataset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "DP synthetic dataset not found."}, status=404)
    if not group_column or not metric_column:
        return JsonResponse({"ok": False, "error": "Choose a grouping column and numeric measure."}, status=400)
    try:
        dataframe = pd.read_csv(dataset.file.path)
    except (OSError, ValueError) as exc:
        return JsonResponse({"ok": False, "error": f"Unable to read the DP dataset: {exc}"}, status=400)
    if group_column not in dataframe or metric_column not in dataframe:
        return JsonResponse({"ok": False, "error": "The selected columns are not in the DP output."}, status=400)
    if not pd.api.types.is_numeric_dtype(dataframe[metric_column]):
        return JsonResponse({"ok": False, "error": "Choose a numeric measure."}, status=400)
    data = dataframe[[group_column, metric_column]].copy()
    data[metric_column] = pd.to_numeric(data[metric_column], errors="coerce")
    data = data.dropna(subset=[group_column, metric_column])
    if data.empty:
        return JsonResponse({"ok": False, "error": "There are no usable synthetic records for these columns."}, status=400)
    data[group_column] = data[group_column].astype(str)
    grouped = data.groupby(group_column, dropna=True)[metric_column].agg(["count", "mean", "median"]).sort_values("count", ascending=False)
    if len(grouped) > 12:
        kept = grouped.iloc[:11]
        other = grouped.iloc[11:]
        grouped = pd.concat([kept, pd.DataFrame({"count": [other["count"].sum()],
                                                   "mean": [(other["mean"] * other["count"]).sum() / other["count"].sum()],
                                                   "median": [float("nan")]}, index=["Other groups"])])
    groups = [{"group": str(index), "count": int(row["count"]), "mean": float(row["mean"]),
               "median": float(row["median"]) if pd.notna(row["median"]) else None}
              for index, row in grouped.iterrows()]
    return JsonResponse({"ok": True, "dataset": dataset.name, "group_column": group_column,
                         "metric_column": metric_column, "records": int(len(data)),
                         "mean": float(data[metric_column].mean()), "median": float(data[metric_column].median()),
                         "min": float(data[metric_column].min()), "max": float(data[metric_column].max()),
                         "groups": groups})


@require_http_methods(["POST"])
def train_analytics_model_api(request):
    """Compare synthetic and real training on the same student-level holdout."""
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        synthetic_id = UUID(str(payload.get("synthetic_id")))
        target = str(payload.get("target") or "").strip()
        model_name = str(payload.get("model") or "Random Forest").strip()
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Choose a DP dataset, target, and model."}, status=400)
    if not target:
        return JsonResponse({"ok": False, "error": "Choose a target column."}, status=400)
    if model_name not in {"XGBoost", "Random Forest", "MLP"}:
        return JsonResponse({"ok": False, "error": "Choose XGBoost, Random Forest, or MLP."}, status=400)

    try:
        synthetic_dataset = Dataset.objects.get(
            id=synthetic_id, stage=Dataset.STAGE_SYNTHETIC, differentially_private=True,
        )
    except Dataset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "DP synthetic dataset not found."}, status=404)
    source_dataset = _get_validation_source(synthetic_dataset)
    if source_dataset is None:
        return JsonResponse({"ok": False, "error": "The DP output has no linked cleaned source."}, status=400)
    try:
        policy = PrivacyPolicy.objects.filter(dataset=source_dataset).first()
        student_id_col = policy.student_id_col if policy else "student_id"
        if not source_dataset.file or not source_dataset.file.name or not synthetic_dataset.file or not synthetic_dataset.file.name:
            return JsonResponse({"ok": False, "error": "A dataset file is missing."}, status=400)
        real_df = pd.read_csv(source_dataset.file.path)
        synthetic_df = pd.read_csv(synthetic_dataset.file.path)
        if target not in real_df or target not in synthetic_df:
            return JsonResponse({"ok": False, "error": f"Target '{target}' must exist in both datasets."}, status=400)
        if student_id_col not in real_df:
            return JsonResponse({"ok": False, "error": f"The cleaned source has no student ID column ('{student_id_col}')."}, status=400)

        from sklearn.compose import ColumnTransformer
        from sklearn.impute import SimpleImputer
        from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, mean_absolute_error, mean_squared_error, precision_score, r2_score, recall_score
        from sklearn.model_selection import GroupShuffleSplit
        from sklearn.neural_network import MLPClassifier, MLPRegressor
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import OneHotEncoder, StandardScaler
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.base import clone

        real_df = real_df.dropna(subset=[target, student_id_col]).copy()
        synthetic_df = synthetic_df.dropna(subset=[target]).copy()
        groups = real_df[student_id_col].astype(str)
        if groups.nunique() < 5:
            return JsonResponse({"ok": False, "error": "At least five identified students are needed for a student-level holdout."}, status=400)
        split = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
        train_idx, test_idx = next(split.split(real_df, groups=groups))
        real_train, real_test = real_df.iloc[train_idx], real_df.iloc[test_idx]
        if real_test[student_id_col].nunique() == 0:
            return JsonResponse({"ok": False, "error": "Could not create a student-level holdout."}, status=400)

        classification = target.lower() in {"pass_fail", "dropout_risk"} or not pd.api.types.is_numeric_dtype(real_df[target])
        if classification:
            y_real = real_df[target].astype(str)
            y_synthetic = synthetic_df[target].astype(str)
            if y_real.nunique() < 2 or y_synthetic.nunique() < 2:
                return JsonResponse({"ok": False, "error": "Classification requires at least two target classes in both datasets."}, status=400)
            estimator_cls = RandomForestClassifier if model_name == "Random Forest" else MLPClassifier
            if model_name == "XGBoost":
                from xgboost import XGBClassifier
                from sklearn.preprocessing import LabelEncoder
                estimator_cls = XGBClassifier
                label_encoder = LabelEncoder().fit(pd.concat([y_real, y_synthetic], ignore_index=True))
                y_real = pd.Series(label_encoder.transform(y_real), index=y_real.index)
                y_synthetic = pd.Series(label_encoder.transform(y_synthetic), index=y_synthetic.index)
        else:
            y_real = pd.to_numeric(real_df[target], errors="coerce")
            y_synthetic = pd.to_numeric(synthetic_df[target], errors="coerce")
            real_df = real_df.loc[y_real.notna()].copy(); y_real = y_real.loc[y_real.notna()]
            synthetic_df = synthetic_df.loc[y_synthetic.notna()].copy(); y_synthetic = y_synthetic.loc[y_synthetic.notna()]
            # Recreate the split after dropping invalid numeric outcomes.
            groups = real_df[student_id_col].astype(str)
            if groups.nunique() < 5:
                return JsonResponse({"ok": False, "error": "At least five students with valid numeric target values are needed for a student-level holdout."}, status=400)
            train_idx, test_idx = next(split.split(real_df, groups=groups))
            real_train, real_test = real_df.iloc[train_idx], real_df.iloc[test_idx]
            y_train_real, y_test = y_real.iloc[train_idx], y_real.iloc[test_idx]
            estimator_cls = RandomForestRegressor if model_name == "Random Forest" else MLPRegressor
            if model_name == "XGBoost":
                from xgboost import XGBRegressor
                estimator_cls = XGBRegressor
        if classification:
            y_train_real = y_real.iloc[train_idx]
            y_test = y_real.iloc[test_idx]

        ignored = {target, student_id_col}
        feature_columns = [column for column in real_df.columns if column not in ignored and column in synthetic_df.columns]
        if not feature_columns:
            return JsonResponse({"ok": False, "error": "No shared feature columns remain after excluding the target and student ID."}, status=400)
        X_synthetic = synthetic_df[feature_columns]
        X_real_train, X_real_test = real_train[feature_columns], real_test[feature_columns]
        numeric_columns = [column for column in feature_columns if pd.api.types.is_numeric_dtype(real_df[column])]
        categorical_columns = [column for column in feature_columns if column not in numeric_columns]
        transformers = []
        if numeric_columns:
            transformers.append(("numeric", make_pipeline(SimpleImputer(strategy="median"), StandardScaler()), numeric_columns))
        if categorical_columns:
            transformers.append(("categorical", make_pipeline(SimpleImputer(strategy="most_frequent"), OneHotEncoder(handle_unknown="ignore")), categorical_columns))
        preprocessor = ColumnTransformer(transformers)
        def build_model():
            if model_name == "MLP":
                estimator = estimator_cls(hidden_layer_sizes=(64, 32), max_iter=300, random_state=42, early_stopping=True)
            elif model_name == "XGBoost":
                estimator = estimator_cls(n_estimators=100, max_depth=4, learning_rate=0.08, n_jobs=1, random_state=42, verbosity=0)
            elif classification:
                estimator = estimator_cls(n_estimators=150, random_state=42, n_jobs=-1, class_weight="balanced")
            else:
                estimator = estimator_cls(n_estimators=150, random_state=42, n_jobs=-1)
            return make_pipeline(clone(preprocessor), estimator)
        synthetic_model = build_model().fit(X_synthetic, y_synthetic)
        real_model = build_model().fit(X_real_train, y_train_real)
        score_fn = accuracy_score if classification else r2_score
        synthetic_predictions = synthetic_model.predict(X_real_test)
        real_predictions = real_model.predict(X_real_test)
        synthetic_score = float(score_fn(y_test, synthetic_predictions))
        real_score = float(score_fn(y_test, real_predictions))
        if not math.isfinite(synthetic_score) or not math.isfinite(real_score):
            raise ValueError("The selected target does not have enough variation to calculate a score.")
        result = {"ok": True, "source": source_dataset.name, "synthetic": synthetic_dataset.name,
                             "target": target, "model": model_name,
                             "metric": "accuracy" if classification else "R²",
                             "synthetic_score": synthetic_score, "real_score": real_score,
                             "gap": synthetic_score - real_score,
                             "train_students": int(real_train[student_id_col].nunique()),
                             "test_students": int(real_test[student_id_col].nunique()),
                             "test_rows": int(len(real_test)), "feature_count": len(feature_columns)}
        if classification:
            labels = sorted(pd.unique(pd.concat([pd.Series(y_test), pd.Series(synthetic_predictions), pd.Series(real_predictions)])), key=str)
            result.update({
                "labels": [str(label) for label in labels],
                "synthetic_confusion_matrix": confusion_matrix(y_test, synthetic_predictions, labels=labels).tolist(),
                "real_confusion_matrix": confusion_matrix(y_test, real_predictions, labels=labels).tolist(),
                "synthetic_precision": float(precision_score(y_test, synthetic_predictions, average="weighted", zero_division=0)),
                "synthetic_recall": float(recall_score(y_test, synthetic_predictions, average="weighted", zero_division=0)),
                "synthetic_f1": float(f1_score(y_test, synthetic_predictions, average="weighted", zero_division=0)),
                "real_precision": float(precision_score(y_test, real_predictions, average="weighted", zero_division=0)),
                "real_recall": float(recall_score(y_test, real_predictions, average="weighted", zero_division=0)),
                "real_f1": float(f1_score(y_test, real_predictions, average="weighted", zero_division=0)),
            })
        else:
            result.update({
                "synthetic_mae": float(mean_absolute_error(y_test, synthetic_predictions)),
                "synthetic_rmse": float(mean_squared_error(y_test, synthetic_predictions) ** 0.5),
                "real_mae": float(mean_absolute_error(y_test, real_predictions)),
                "real_rmse": float(mean_squared_error(y_test, real_predictions) ** 0.5),
            })
        return JsonResponse(result)
    except (ValueError, KeyError, IndexError, OSError, ImportError, TypeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_http_methods(["POST"])
def simulate_preview(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        schema = payload.get("schema")
        n_rows = int(payload.get("n_rows", 100))
        seed = payload.get("seed")
        rows_per_student = int(payload.get("rows_per_student", 1))
        dataframe = simulate(schema=schema, n_rows=n_rows, seed=seed, rows_per_student=rows_per_student)
        preview = dataframe.head(10).to_dict(orient="records")
        return JsonResponse({
            "ok": True,
            "rows": preview,
            "columns": list(dataframe.columns),
            "n_rows": len(dataframe),
        })
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@require_http_methods(["POST"])
def simulate_generate(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        schema = payload.get("schema")
        n_rows = int(payload.get("n_rows", 100))
        seed = payload.get("seed")
        rows_per_student = int(payload.get("rows_per_student", 1))

        dataframe = simulate(schema=schema, n_rows=n_rows, seed=seed, rows_per_student=rows_per_student)
        dataset = Dataset(
            name=f"simulated_dataset_{len(Dataset.objects.all()) + 1}",
            stage=Dataset.STAGE_SIMULATED,
            rows=int(len(dataframe)),
            cols=int(len(dataframe.columns)),
        )

        csv_content = dataframe.to_csv(index=False)
        filename = f"simulated_{dataset.id}.csv"
        dataset.file.save(filename, ContentFile(csv_content.encode("utf-8")), save=False)
        dataset.save()

        return JsonResponse({
            "ok": True,
            "dataset_id": str(dataset.id),
            "rows": dataset.rows,
            "columns": dataset.cols,
            "dtypes": [str(dtype) for dtype in dataframe.dtypes],
        })
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


def download_dataset(request, dataset_id):
    try:
        dataset = Dataset.objects.get(id=UUID(str(dataset_id)))
    except Dataset.DoesNotExist as exc:
        raise Http404("Dataset not found.") from exc

    if not dataset.file or not dataset.file.name:
        raise Http404("Dataset file is missing.")

    filename = Path(dataset.file.name).name
    response = FileResponse(dataset.file.open("rb"), as_attachment=True, filename=filename)
    response["Content-Type"] = "text/csv"
    return response


@require_http_methods(["GET", "POST"])
def upload_dataset(request):
    if request.method == "GET":
        return api_datasets(request)

    file = request.FILES.get("file")
    if not file:
        return JsonResponse({"ok": False, "error": "A CSV file is required."}, status=400)

    if not file.name.lower().endswith(".csv"):
        return JsonResponse({"ok": False, "error": "Only CSV files are allowed."}, status=400)

    if file.size > 10 * 1024 * 1024:
        return JsonResponse({"ok": False, "error": "Upload size must be 10 MB or smaller."}, status=400)

    try:
        df = pd.read_csv(file)
    except Exception as exc:  # pragma: no cover - depends on malformed CSV input
        return JsonResponse({"ok": False, "error": f"Unable to parse CSV: {exc}"}, status=400)

    dataset = Dataset.objects.create(
        name=file.name,
        stage=Dataset.STAGE_RAW,
        rows=int(len(df)),
        cols=int(len(df.columns)),
        file=file,
    )

    return JsonResponse({
        "ok": True,
        "dataset_id": str(dataset.id),
        "profile": profile(df),
    })


@require_http_methods(["POST"])
def clean_dataset(request):
    try:
        if request.content_type.startswith("application/json"):
            payload = json.loads(request.body.decode("utf-8") or "{}")
        else:
            payload = {"dataset_id": request.POST.get("dataset_id"), "options": json.loads(request.POST.get("options") or "{}")}
    except json.JSONDecodeError as exc:
        return JsonResponse({"ok": False, "error": f"Invalid JSON: {exc}"}, status=400)

    dataset_id = payload.get("dataset_id")
    options = payload.get("options") or {}
    if not dataset_id:
        return JsonResponse({"ok": False, "error": "dataset_id is required."}, status=400)

    try:
        dataset = Dataset.objects.get(id=UUID(str(dataset_id)))
    except Dataset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Dataset not found."}, status=404)

    if not dataset.file or not dataset.file.name:
        return JsonResponse({"ok": False, "error": "Dataset file is missing."}, status=400)

    try:
        df = pd.read_csv(dataset.file.path)
    except Exception as exc:  # pragma: no cover - depends on malformed CSV input
        return JsonResponse({"ok": False, "error": f"Unable to read dataset: {exc}"}, status=400)

    cleaned_df, report = clean(df, options)
    cleaned_name = f"cleaned_{dataset.id}.csv"
    csv_content = cleaned_df.to_csv(index=False)

    cleaned_dataset = Dataset.objects.create(
        name=cleaned_name,
        stage=Dataset.STAGE_CLEANED,
        rows=int(len(cleaned_df)),
        cols=int(len(cleaned_df.columns)),
    )
    cleaned_dataset.file.save(cleaned_name, ContentFile(csv_content.encode("utf-8")), save=False)
    cleaned_dataset.save()

    report["missing_cells"] = int(cleaned_df.isna().sum().sum())

    return JsonResponse({
        "ok": True,
        "dataset_id": str(cleaned_dataset.id),
        "report": report,
        "profile": profile(cleaned_df),
        "preview": cleaned_df.head(10).to_dict(orient="records"),
    })


@require_http_methods(["POST"])
def validate_dataset_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        return JsonResponse({"ok": False, "error": f"Invalid JSON: {exc}"}, status=400)

    dataset_id = payload.get("dataset_id")
    if not dataset_id:
        return JsonResponse({"ok": False, "error": "dataset_id is required."}, status=400)

    try:
        dataset = Dataset.objects.get(id=UUID(str(dataset_id)), stage=Dataset.STAGE_SYNTHETIC,
                                      differentially_private=True)
    except (Dataset.DoesNotExist, ValueError):
        return JsonResponse({"ok": False, "error": "Dataset not found."}, status=404)

    if not dataset.file or not dataset.file.name:
        return JsonResponse({"ok": False, "error": "Synthetic dataset file is missing."}, status=400)

    source_dataset = _get_validation_source(dataset)
    if source_dataset is None or not source_dataset.file or not source_dataset.file.name:
        return JsonResponse({"ok": False, "error": "No cleaned source dataset is linked to this DP output."}, status=400)

    try:
        real_df = pd.read_csv(source_dataset.file.path)
        synthetic_df = pd.read_csv(dataset.file.path)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Unable to read dataset: {exc}"}, status=400)

    if real_df.empty or synthetic_df.empty or len(real_df.columns) == 0 or len(synthetic_df.columns) == 0:
        return JsonResponse({"ok": False, "error": "The source or synthetic dataset has no records or columns."}, status=400)

    fidelity = evaluate_fidelity(real_df, synthetic_df)
    if "error" in fidelity["details"]:
        return JsonResponse({"ok": False, "error": fidelity["details"]["error"]}, status=400)
    return JsonResponse({
        "ok": True, "score": fidelity["score"], "details": fidelity["details"],
        "source": {"id": str(source_dataset.id), "name": source_dataset.name,
                   "rows": len(real_df), "columns": len(real_df.columns)},
        "synthetic": {"id": str(dataset.id), "name": dataset.name,
                      "rows": len(synthetic_df), "columns": len(synthetic_df.columns)},
    })


@require_http_methods(["POST"])
def privacy_dataset_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        return JsonResponse({"ok": False, "error": f"Invalid JSON: {exc}"}, status=400)

    synthetic_id = payload.get("synthetic_id")
    if not synthetic_id:
        return JsonResponse({"ok": False, "error": "synthetic_id is required."}, status=400)

    try:
        synthetic_dataset = Dataset.objects.get(
            id=UUID(str(synthetic_id)), stage=Dataset.STAGE_SYNTHETIC,
            differentially_private=True,
        )
    except (Dataset.DoesNotExist, ValueError):
        return JsonResponse({"ok": False, "error": "Dataset not found."}, status=404)

    real_dataset = _get_validation_source(synthetic_dataset)
    if real_dataset is None:
        return JsonResponse({"ok": False, "error": "No cleaned source dataset is linked to this DP output."}, status=400)

    if not real_dataset.file or not synthetic_dataset.file:
        return JsonResponse({"ok": False, "error": "Dataset files are missing."}, status=400)

    try:
        real_df = pd.read_csv(real_dataset.file.path)
        synthetic_df = pd.read_csv(synthetic_dataset.file.path)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Unable to read dataset: {exc}"}, status=400)

    job_id = str(UUID(int=len(_JOB_STORE) + 1))
    _JOB_STORE[job_id] = {"status": "running", "created_at": pd.Timestamp.utcnow().isoformat()}

    try:
        result = run_privacy_check(real_df, synthetic_df)
        _JOB_STORE[job_id] = {
            "status": "completed",
            "created_at": pd.Timestamp.utcnow().isoformat(),
            "result": result,
        }
    except Exception as exc:
        _JOB_STORE[job_id] = {"status": "failed", "error": str(exc)}
        return JsonResponse({"ok": False, "error": str(exc)}, status=500)

    return JsonResponse({"ok": True, "job_id": job_id, "status": "completed",
                         "source": {"id": str(real_dataset.id), "name": real_dataset.name},
                         "synthetic": {"id": str(synthetic_dataset.id), "name": synthetic_dataset.name}})


@require_http_methods(["POST"])
def utility_evaluation_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        synthetic_id = UUID(str(payload.get("synthetic_id")))
        target = str(payload.get("target") or "").strip()
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Choose a synthetic dataset and numeric target."}, status=400)
    if not target:
        return JsonResponse({"ok": False, "error": "Choose a numeric target column."}, status=400)

    try:
        synthetic_dataset = Dataset.objects.get(
            id=synthetic_id, stage=Dataset.STAGE_SYNTHETIC,
            differentially_private=True,
        )
    except Dataset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "DP synthetic dataset not found."}, status=404)
    source_dataset = _get_validation_source(synthetic_dataset)
    if source_dataset is None:
        return JsonResponse({"ok": False, "error": "No cleaned source dataset is linked to this DP output."}, status=400)

    try:
        real_df = pd.read_csv(source_dataset.file.path)
        synthetic_df = pd.read_csv(synthetic_dataset.file.path)
        result = evaluate_utility(real_df, synthetic_df, target)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Utility evaluation failed: {exc}"}, status=500)

    policy = PrivacyPolicy.objects.filter(dataset=source_dataset).first()
    return JsonResponse({
        "ok": True, "result": result,
        "epsilon": policy.epsilon if policy else None,
        "source": {"id": str(source_dataset.id), "name": source_dataset.name, "rows": len(real_df)},
        "synthetic": {"id": str(synthetic_dataset.id), "name": synthetic_dataset.name,
                      "rows": len(synthetic_df)},
    })


@require_http_methods(["GET"])
def privacy_utility_options_api(request):
    try:
        synthetic_id = UUID(str(request.GET.get("synthetic_id")))
        synthetic_dataset = Dataset.objects.get(
            id=synthetic_id, stage=Dataset.STAGE_SYNTHETIC,
            differentially_private=True,
        )
    except (ValueError, Dataset.DoesNotExist):
        return JsonResponse({"ok": False, "error": "Choose a valid DP synthetic dataset."}, status=400)
    source_dataset = _get_validation_source(synthetic_dataset)
    if source_dataset is None:
        return JsonResponse({"ok": False, "error": "No cleaned source dataset is linked to this DP output."}, status=400)
    try:
        policy = PrivacyPolicy.objects.get(dataset=source_dataset)
    except PrivacyPolicy.DoesNotExist:
        return JsonResponse({"ok": False, "error": "The source dataset has no saved privacy policy."}, status=404)

    ledger = list(BudgetLedger.objects.filter(dataset=source_dataset))
    epsilon_spent = sum(item.epsilon_spent for item in ledger)
    delta_spent = sum(item.delta for item in ledger)
    epsilon_remaining = max(float(policy.epsilon) - epsilon_spent, 0.0)
    delta_remaining = max(float(policy.delta) - delta_spent, 0.0)
    first_epsilon = round(epsilon_remaining * 0.2, 8)
    second_epsilon = round(epsilon_remaining * 0.3, 8)
    suggested_epsilons = [first_epsilon, second_epsilon,
                          max(epsilon_remaining - first_epsilon - second_epsilon, 0.0)]
    return JsonResponse({
        "ok": True,
        "source": {"id": str(source_dataset.id), "name": source_dataset.name},
        "synthetic": {"id": str(synthetic_dataset.id), "name": synthetic_dataset.name,
                      "rows": synthetic_dataset.rows},
        "epsilon_cap": float(policy.epsilon), "epsilon_spent": epsilon_spent,
        "epsilon_remaining": epsilon_remaining,
        "delta_cap": float(policy.delta), "delta_spent": delta_spent,
        "delta_remaining": delta_remaining,
        "suggested_epsilons": suggested_epsilons,
    })


@transaction.atomic
@require_http_methods(["POST"])
def privacy_utility_sweep_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        synthetic_id = UUID(str(payload.get("synthetic_id")))
        target = str(payload.get("target") or "").strip()
        raw_epsilons = payload.get("epsilons")
        if not isinstance(raw_epsilons, list):
            raise ValueError
        epsilons = [float(value) for value in raw_epsilons]
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Choose a dataset, numeric target, and valid epsilon values."}, status=400)
    if not target:
        return JsonResponse({"ok": False, "error": "Choose a numeric prediction target."}, status=400)
    if not 2 <= len(epsilons) <= 5 or any(not math.isfinite(value) or value <= 0 for value in epsilons):
        return JsonResponse({"ok": False, "error": "Enter between 2 and 5 positive epsilon values."}, status=400)
    if len(set(epsilons)) != len(epsilons):
        return JsonResponse({"ok": False, "error": "Each epsilon value must be different."}, status=400)

    try:
        synthetic_dataset = Dataset.objects.select_for_update().get(
            id=synthetic_id, stage=Dataset.STAGE_SYNTHETIC,
            differentially_private=True,
        )
    except Dataset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "DP synthetic dataset not found."}, status=404)
    source_dataset = _get_validation_source(synthetic_dataset)
    if source_dataset is None:
        return JsonResponse({"ok": False, "error": "No cleaned source dataset is linked to this DP output."}, status=400)
    try:
        policy = PrivacyPolicy.objects.select_for_update().get(dataset=source_dataset)
    except PrivacyPolicy.DoesNotExist:
        return JsonResponse({"ok": False, "error": "The source dataset has no saved privacy policy."}, status=404)

    ledger = list(BudgetLedger.objects.filter(dataset=source_dataset))
    epsilon_spent = sum(item.epsilon_spent for item in ledger)
    delta_spent = sum(item.delta for item in ledger)
    epsilon_requested = sum(epsilons)
    delta_remaining = max(float(policy.delta) - delta_spent, 0.0)
    if epsilon_spent + epsilon_requested > float(policy.epsilon) + 1e-12:
        return JsonResponse({"ok": False, "error": f"This sweep needs ε={epsilon_requested:.4g}; only ε={max(float(policy.epsilon) - epsilon_spent, 0):.4g} remains. Increase the privacy budget in Configure Privacy Mechanism."}, status=400)
    if delta_remaining <= 0:
        return JsonResponse({"ok": False, "error": "No δ budget remains for a sweep. Increase the delta budget in Configure Privacy Mechanism."}, status=400)

    try:
        if not source_dataset.file or not source_dataset.file.name:
            return JsonResponse({"ok": False, "error": "The linked cleaned source file is missing."}, status=400)
        if not synthetic_dataset.file or not synthetic_dataset.file.name:
            return JsonResponse({"ok": False, "error": "The selected DP synthetic file is missing."}, status=400)
        real_df = pd.read_csv(source_dataset.file.path)
        selected_synthetic_df = pd.read_csv(synthetic_dataset.file.path)
        if real_df.empty or selected_synthetic_df.empty:
            return JsonResponse({"ok": False, "error": "The linked source and selected DP synthetic files must both contain records."}, status=400)
        if target not in real_df.columns or target not in selected_synthetic_df.columns:
            return JsonResponse({"ok": False, "error": f"Target '{target}' must exist in both the linked source and selected DP synthetic file."}, status=400)
        source_target_count = int(pd.to_numeric(real_df[target], errors="coerce").notna().sum())
        selected_target_count = int(pd.to_numeric(selected_synthetic_df[target], errors="coerce").notna().sum())
        if source_target_count < 3 or selected_target_count < 2:
            return JsonResponse({"ok": False, "error": f"The linked files need at least 3 real and 2 selected synthetic '{target}' values. Found {source_target_count} real and {selected_target_count} synthetic."}, status=400)
        student_count = int(real_df[policy.student_id_col].nunique(dropna=True)) if policy.student_id_col in real_df else 0
        if not student_count:
            return JsonResponse({"ok": False, "error": "The source does not contain students identified by the saved policy."}, status=400)
        delta_per_run = delta_remaining / len(epsilons)
        delta_limit = 1 / student_count
        if float(policy.delta) >= delta_limit or delta_per_run >= delta_limit:
            return JsonResponse({"ok": False, "error": f"For {student_count} students, the configured total delta budget and each per-run delta must be less than 1 / {student_count} ({delta_limit:.6g}). Lower the delta value in Configure Privacy Mechanism."}, status=400)

        results = []
        ledger_entries = []
        for epsilon in sorted(epsilons):
            run_policy = copy.copy(policy)
            run_policy.epsilon = epsilon
            run_policy.delta = delta_per_run
            private_df, metadata = generate_dp_synthetic(
                real_df, policy=run_policy,
                n_rows=len(selected_synthetic_df), seed=42,
            )
            if target not in private_df.columns:
                raise ValueError(f"Generated data at ε={epsilon:g} does not contain target '{target}'.")
            utility = evaluate_utility(real_df, private_df, target)
            privacy = run_privacy_check(real_df, private_df)
            results.append({
                "epsilon": epsilon,
                "delta": delta_per_run,
                "generated_rows": int(len(private_df)),
                "utility_score": utility["utility_score"],
                "tstr_r2": utility["tstr_r2"],
                "tstr_diagnostics": utility["tstr_diagnostics"],
                "baseline_score": utility["baseline_score"],
                "utility_vs_baseline": utility["utility_vs_baseline"],
                "mia_auc": privacy["membership_inference"]["attack_auc"],
                "exact_match_pct": privacy["exact_match_pct"],
                "verdict": privacy["verdict"],
                "privacy_unit": metadata["privacy_unit"],
            })
            ledger_entries.append(BudgetLedger(
                dataset=source_dataset,
                action=f"PAC-Synth privacy-utility sweep ε={epsilon:g}",
                epsilon_spent=epsilon,
                delta=delta_per_run,
            ))
        BudgetLedger.objects.bulk_create(ledger_entries)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except RuntimeError as exc:
        # PAC-Synth can fail on an infeasible noisy count. This is a model
        # configuration/data failure, not an unhandled server exception.
        return JsonResponse({"ok": False, "error": f"Privacy-utility sweep could not synthesize this point: {exc}"}, status=422)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Privacy-utility sweep failed: {exc}"}, status=500)

    safe_results = [row for row in results if row["mia_auc"] <= 0.6]
    recommended = (max(safe_results, key=lambda row: row["utility_score"])
                   if safe_results else min(results, key=lambda row: row["mia_auc"]))
    return JsonResponse({
        "ok": True, "results": results, "recommended_epsilon": recommended["epsilon"],
        "recommendation_note": ("Best utility among sweep points with MIA AUC at or below 0.6."
                                if safe_results else "No sweep point met the MIA AUC threshold; this is the lowest-risk point tested."),
        "epsilon_spent": epsilon_spent + epsilon_requested,
        "epsilon_remaining": max(float(policy.epsilon) - epsilon_spent - epsilon_requested, 0.0),
        "delta_spent": delta_spent + delta_remaining,
        "delta_remaining": 0.0,
        "source": {"id": str(source_dataset.id), "name": source_dataset.name},
        "synthetic": {"id": str(synthetic_dataset.id), "name": synthetic_dataset.name},
        "source_rows": int(len(real_df)),
        "reference_rows": int(len(selected_synthetic_df)),
        "reference_valid_target_rows": selected_target_count,
    })


@require_http_methods(["GET"])
def jobs_api(request):
    return JsonResponse({"ok": True, "jobs": list(_JOB_STORE.keys())})


@require_http_methods(["GET"])
def job_result_api(request, job_id):
    job = _JOB_STORE.get(job_id)
    if not job:
        return JsonResponse({"ok": False, "error": "Job not found."}, status=404)
    return JsonResponse({"ok": True, "job_id": job_id, "job": job})


@require_http_methods(["GET"])
def api_datasets(request):
    datasets = Dataset.objects.all()
    stage = request.GET.get("stage")
    if stage:
        datasets = datasets.filter(stage=stage)
    if request.GET.get("dp") == "true":
        datasets = datasets.filter(differentially_private=True)
    return JsonResponse({"ok": True, "datasets": [
        {"id": str(item.id), "name": item.name, "stage": item.stage, "rows": item.rows, "cols": item.cols,
         "differentially_private": item.differentially_private,
         "source_dataset_id": str(source.id) if source else None,
         "source_dataset_name": source.name if source else None}
        for item in datasets
        for source in [_get_validation_source(item) if item.stage == Dataset.STAGE_SYNTHETIC and item.differentially_private else None]
    ]})


def _get_validation_source(dataset):
    """Get the cleaned source for a synthetic output, including legacy outputs."""
    source = dataset.source_dataset if dataset.source_dataset_id else None
    if source is None and dataset.name.startswith("dp_synthetic_"):
        legacy_id = dataset.name.removeprefix("dp_synthetic_").removesuffix(".csv")
        try:
            source = Dataset.objects.get(id=UUID(legacy_id), stage=Dataset.STAGE_CLEANED)
        except (ValueError, Dataset.DoesNotExist):
            source = None
    if source is not None and source.stage == Dataset.STAGE_CLEANED:
        return source
    return None


@require_http_methods(["GET"])
def dataset_profile_api(request, dataset_id):
    try:
        dataset = Dataset.objects.get(id=dataset_id)
    except Dataset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Dataset not found."}, status=404)
    if dataset.stage != Dataset.STAGE_CLEANED:
        return JsonResponse({"ok": False, "error": "Choose a cleaned dataset."}, status=400)
    try:
        dataframe = pd.read_csv(dataset.file.path)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Unable to read dataset: {exc}"}, status=400)
    student_id_col = request.GET.get("student_id_col", "student_id")
    students = int(dataframe[student_id_col].nunique(dropna=True)) if student_id_col in dataframe else 0
    columns = list(dataframe.columns)
    average_rows = round(len(dataframe) / students, 2) if students else 0
    return JsonResponse({"ok": True, "dataset": {"id": str(dataset.id), "name": dataset.name, "rows": len(dataframe)},
                         "columns": columns, "students": students, "average_rows_per_student": average_rows,
                         "profile": profile(dataframe),
                         "default_public_bounds": public_bounds_for_columns(columns)})


@require_http_methods(["GET"])
def synthetic_preview_api(request, dataset_id):
    try:
        dataset = Dataset.objects.get(id=dataset_id, stage=Dataset.STAGE_SYNTHETIC, differentially_private=True)
        dataframe = pd.read_csv(dataset.file.path)
    except Dataset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "DP synthetic dataset not found."}, status=404)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Unable to read synthetic dataset: {exc}"}, status=400)
    rows = dataframe.head(20).astype(object).where(pd.notna(dataframe.head(20)), None).to_dict(orient="records")
    return JsonResponse({"ok": True, "dataset": {"id": str(dataset.id), "name": dataset.name,
                                                    "rows": dataset.rows, "cols": dataset.cols},
                         "columns": list(dataframe.columns), "preview": rows,
                         "download_url": f"/api/datasets/{dataset.id}/download/"})


@require_http_methods(["POST"])
def privacy_policy_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        dataset = Dataset.objects.get(id=UUID(str(payload.get("dataset_id"))), stage=Dataset.STAGE_CLEANED)
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "A valid cleaned dataset is required."}, status=400)
    except Dataset.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Cleaned dataset not found."}, status=404)

    student_id_col = str(payload.get("student_id_col") or "student_id")
    try:
        dataframe = pd.read_csv(dataset.file.path)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Unable to read dataset: {exc}"}, status=400)
    if student_id_col not in dataframe.columns:
        return JsonResponse({"ok": False, "error": f"Student ID column '{student_id_col}' is not in this dataset."}, status=400)

    quasi_identifiers = payload.get("quasi_identifiers") or []
    sensitive_attributes = payload.get("sensitive_attributes") or []
    raw_bounds = payload.get("public_bounds") or {}
    if not isinstance(raw_bounds, dict):
        return JsonResponse({"ok": False, "error": "Public numeric bounds must be an object."}, status=400)
    public_bounds = {}
    for column, pair in raw_bounds.items():
        if column not in dataframe.columns or not isinstance(pair, dict):
            continue
        try:
            lower, upper = float(pair.get("lower")), float(pair.get("upper"))
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": f"Enter numeric public bounds for '{column}'."}, status=400)
        if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
            return JsonResponse({"ok": False, "error": f"Public lower bound for '{column}' must be below its upper bound."}, status=400)
        public_bounds[column] = [lower, upper]
    quasi_identifiers = [column for column in quasi_identifiers if column in dataframe.columns and column != student_id_col]
    sensitive_attributes = [column for column in sensitive_attributes if column in dataframe.columns and column != student_id_col]
    try:
        max_rows = max(1, int(payload.get("max_rows_per_student", 1)))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Max rows per student must be a whole number."}, status=400)
    policy, _ = PrivacyPolicy.objects.update_or_create(
        dataset=dataset,
        defaults={"privacy_unit": "student", "student_id_col": student_id_col,
                  "max_rows_per_student": max_rows, "quasi_identifiers": quasi_identifiers,
                  "public_bounds": public_bounds,
                  "sensitive_attributes": sensitive_attributes, "status": "configured",
                  "accountant": PrivacyPolicy.ACCOUNTANT_PAC_SYNTH, "reporting_length": 2},
    )
    scan = risk_scan(dataframe, {"student_id_col": student_id_col,
                                 "quasi_identifiers": quasi_identifiers,
                                 "sensitive_attributes": sensitive_attributes})
    return JsonResponse({"ok": True, "policy_id": policy.id, "students": scan["n_students"], "risk_scan": scan})


@transaction.atomic
@require_http_methods(["POST"])
def privacy_budget_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        dataset_id = UUID(str(payload.get("dataset_id")))
        epsilon = float(payload.get("epsilon"))
        delta = float(payload.get("delta"))
        reporting_length = int(payload.get("reporting_length", 2))
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Enter valid privacy settings and choose a dataset."}, status=400)
    if not math.isfinite(epsilon) or not math.isfinite(delta) or epsilon <= 0 or not 0 < delta < 1 or reporting_length not in (1, 2, 3):
        return JsonResponse({"ok": False, "error": "Epsilon and delta must be positive; reporting length must be 1, 2, or 3."}, status=400)
    try:
        dataset = Dataset.objects.get(id=dataset_id, stage=Dataset.STAGE_CLEANED)
        policy = PrivacyPolicy.objects.select_for_update().get(dataset=dataset)
    except (Dataset.DoesNotExist, PrivacyPolicy.DoesNotExist):
        return JsonResponse({"ok": False, "error": "Save a student-level privacy policy for this cleaned dataset first."}, status=404)
    try:
        dataframe = pd.read_csv(dataset.file.path)
        if policy.student_id_col not in dataframe.columns:
            return JsonResponse({"ok": False, "error": f"Student ID column '{policy.student_id_col}' is missing from the cleaned dataset."}, status=400)
        students = int(dataframe[policy.student_id_col].nunique(dropna=True))
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"Unable to inspect student count: {exc}"}, status=400)
    if students < 1:
        return JsonResponse({"ok": False, "error": "The cleaned dataset must contain at least one identified student."}, status=400)
    delta_limit = 1.0 / students
    if delta >= delta_limit:
        return JsonResponse({"ok": False, "error": f"For {students} students, delta must be less than 1 / {students} ({delta_limit:.6g}). Enter a smaller delta budget."}, status=400)
    spent = sum(item.epsilon_spent for item in BudgetLedger.objects.filter(dataset=dataset))
    if spent > epsilon:
        return JsonResponse({"ok": False, "error": f"Epsilon {epsilon} is below the {spent:.4g} already spent on this dataset."}, status=400)
    delta_spent = sum(item.delta for item in BudgetLedger.objects.filter(dataset=dataset))
    if delta_spent > delta:
        return JsonResponse({"ok": False, "error": f"Delta {delta} is below the {delta_spent:.4g} already spent on this dataset."}, status=400)
    policy.epsilon = epsilon
    policy.delta = delta
    policy.reporting_length = reporting_length
    policy.accountant = PrivacyPolicy.ACCOUNTANT_PAC_SYNTH
    policy.status = "configured"
    policy.save(update_fields=["epsilon", "delta", "reporting_length", "accountant", "status"])
    return JsonResponse({"ok": True, "epsilon": epsilon, "delta": delta, "reporting_length": reporting_length})


@transaction.atomic
@require_http_methods(["POST"])
def train_dp_generator_api(request):
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
        dataset_id = UUID(str(payload.get("dataset_id")))
        n_rows = int(payload.get("n_rows", 500))
        seed = int(payload.get("seed", 42))
    except (json.JSONDecodeError, TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Choose a dataset and enter valid generation settings."}, status=400)
    if not 1 <= n_rows <= 100000:
        return JsonResponse({"ok": False, "error": "Output rows must be between 1 and 100,000."}, status=400)
    try:
        dataset = Dataset.objects.get(id=dataset_id, stage=Dataset.STAGE_CLEANED)
        policy = PrivacyPolicy.objects.select_for_update().get(dataset=dataset)
    except (Dataset.DoesNotExist, PrivacyPolicy.DoesNotExist):
        return JsonResponse({"ok": False, "error": "A cleaned dataset with a saved student privacy policy is required."}, status=404)
    if policy.accountant != PrivacyPolicy.ACCOUNTANT_PAC_SYNTH:
        return JsonResponse({"ok": False, "error": "Configure the PAC-Synth privacy mechanism before training."}, status=400)

    try:
        real_df = pd.read_csv(dataset.file.path)
        students = int(real_df[policy.student_id_col].nunique(dropna=True)) if policy.student_id_col in real_df else 0
        delta_limit = 1 / students if students else 0
        if not students or policy.delta >= delta_limit:
            return JsonResponse({"ok": False, "error": "Delta must be less than 1 / number of students. Update the privacy mechanism."}, status=400)
        observed_max = int(real_df.groupby(policy.student_id_col, dropna=True).size().max())
        if observed_max > policy.max_rows_per_student:
            return JsonResponse({"ok": False, "error": "Observed rows per student exceed the saved contribution bound."}, status=400)
        ledger = BudgetLedger.objects.filter(dataset=dataset)
        spent = sum(item.epsilon_spent for item in ledger)
        delta_spent = sum(item.delta for item in ledger)
        run_epsilon = float(policy.epsilon) - spent
        run_delta = float(policy.delta) - delta_spent
        if run_epsilon <= 0:
            return JsonResponse({"ok": False, "error": "No epsilon budget remains for this dataset. Increase the configured epsilon cap before training."}, status=400)
        if run_delta <= 0:
            return JsonResponse({"ok": False, "error": "No delta budget remains for this dataset. Increase the configured delta cap before training."}, status=400)
        BudgetLedger.enforce_cap(spent, policy.epsilon, run_epsilon)
        run_policy = copy.copy(policy)
        run_policy.epsilon = run_epsilon
        run_policy.delta = run_delta
        private_df, metadata = generate_dp_synthetic(real_df, policy=run_policy, n_rows=n_rows, seed=seed)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    except RuntimeError as exc:
        return JsonResponse({"ok": False, "error": f"DP generator could not synthesize this dataset: {exc}"}, status=422)
    except Exception as exc:
        return JsonResponse({"ok": False, "error": f"DP generator failed: {exc}"}, status=500)

    synthetic_name = f"dp_synthetic_{dataset.id}.csv"
    result_dataset = Dataset.objects.create(name=synthetic_name, stage=Dataset.STAGE_SYNTHETIC,
                                            rows=int(len(private_df)), cols=int(len(private_df.columns)),
                                            differentially_private=True, source_dataset=dataset)
    result_dataset.file.save(synthetic_name, ContentFile(private_df.to_csv(index=False).encode("utf-8")), save=True)
    BudgetLedger.objects.create(dataset=dataset, action="PAC-Synth student-level synthetic generation",
                                epsilon_spent=run_epsilon, delta=run_delta)
    preview = private_df.head(10).astype(object).where(pd.notna(private_df.head(10)), None).to_dict(orient="records")
    return JsonResponse({"ok": True, "dataset_id": str(result_dataset.id), "rows": len(private_df),
                         "columns": list(private_df.columns), "preview": preview,
                         "privacy": metadata, "download_url": f"/api/datasets/{result_dataset.id}/download/"})
