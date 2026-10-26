"""Simulation utilities for generating synthetic tabular datasets."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from faker import Faker


SUPPORTED_TYPES = {
    "name",
    "email",
    "phone",
    "address",
    "city",
    "country",
    "company",
    "job",
    "date",
    "datetime",
    "uuid",
    "text",
    "integer",
    "float",
    "categorical",
    "boolean",
}


def _normalize_missing_pct(column: dict[str, Any]) -> float:
    params = column.get("params") or {}
    raw_value = column.get("missing_pct", params.get("missing_pct", 0.0))
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive validation
        raise ValueError(f"Invalid missing_pct for column '{column.get('name', '')}'.") from exc
    if value < 0 or value > 1:
        raise ValueError(f"missing_pct must be between 0 and 1 for column '{column.get('name', '')}'.")
    return value


def _generate_faker_series(fake: Faker, dtype: str, n_rows: int, params: dict[str, Any]) -> pd.Series:
    if dtype == "name":
        values = [fake.name() for _ in range(n_rows)]
    elif dtype == "email":
        values = [fake.email() for _ in range(n_rows)]
    elif dtype == "phone":
        values = [fake.phone_number() for _ in range(n_rows)]
    elif dtype == "address":
        values = [fake.street_address() + ", " + fake.city() for _ in range(n_rows)]
    elif dtype == "city":
        values = [fake.city() for _ in range(n_rows)]
    elif dtype == "country":
        values = [fake.country() for _ in range(n_rows)]
    elif dtype == "company":
        values = [fake.company() for _ in range(n_rows)]
    elif dtype == "job":
        values = [fake.job() for _ in range(n_rows)]
    elif dtype == "date":
        values = [fake.date_between(start_date="-10y", end_date="today").isoformat() for _ in range(n_rows)]
    elif dtype == "datetime":
        values = [fake.date_time_between(start_date="-10y", end_date="now").isoformat(timespec="seconds") for _ in range(n_rows)]
    elif dtype == "uuid":
        values = [fake.uuid4() for _ in range(n_rows)]
    elif dtype == "text":
        max_chars = int(params.get("max_chars", 120))
        values = [fake.text(max_nb_chars=max_chars) for _ in range(n_rows)]
    else:  # pragma: no cover - unreachable due to validation
        raise ValueError(f"Unsupported faker dtype: {dtype}")
    return pd.Series(values)


def _generate_integer_series(rng: np.random.Generator, n_rows: int, params: dict[str, Any]) -> pd.Series:
    low = int(params.get("min", 0))
    high = int(params.get("max", 100))
    if low > high:
        low, high = high, low
    values = rng.integers(low, high + 1, size=n_rows)
    return pd.Series(values)


def _generate_float_series(rng: np.random.Generator, n_rows: int, params: dict[str, Any]) -> pd.Series:
    distribution = str(params.get("distribution", "normal")).lower()
    if distribution == "normal":
        mean = float(params.get("mean", 0))
        std = float(params.get("std", 1))
        values = rng.normal(loc=mean, scale=std, size=n_rows)
    elif distribution == "uniform":
        low = float(params.get("min", 0))
        high = float(params.get("max", 1))
        values = rng.uniform(low=low, high=high, size=n_rows)
    elif distribution == "lognormal":
        mean = float(params.get("mean", 0))
        std = float(params.get("std", 1))
        values = rng.lognormal(mean=mean, sigma=std, size=n_rows)
    else:
        raise ValueError(f"Unsupported float distribution: {distribution}")

    min_value = params.get("min")
    max_value = params.get("max")
    if min_value is not None:
        values = np.clip(values, float(min_value), np.inf)
    if max_value is not None:
        values = np.clip(values, -np.inf, float(max_value))
    return pd.Series(values)


def _generate_categorical_series(rng: np.random.Generator, n_rows: int, params: dict[str, Any]) -> pd.Series:
    values = params.get("values") or []
    if not isinstance(values, list) or not values:
        raise ValueError("Categorical columns require a non-empty values list.")
    weights = params.get("weights")
    if weights is None:
        choices = rng.choice(values, size=n_rows)
    else:
        if not isinstance(weights, list) or len(weights) != len(values):
            raise ValueError("Categorical weights must be a list matching the number of values.")
        weights_arr = np.array(weights, dtype=float)
        if np.sum(weights_arr) <= 0:
            raise ValueError("Categorical weights must sum to a positive number.")
        probs = weights_arr / np.sum(weights_arr)
        choices = rng.choice(values, size=n_rows, p=probs)
    return pd.Series(choices)


def _generate_boolean_series(rng: np.random.Generator, n_rows: int, params: dict[str, Any]) -> pd.Series:
    probability = float(params.get("probability", 0.5))
    if probability < 0 or probability > 1:
        raise ValueError("Boolean probability must be between 0 and 1.")
    return pd.Series(rng.random(n_rows) < probability)


def simulate_academic_records(n_rows: int, rows_per_student: int = 1, seed: int | None = None) -> pd.DataFrame:
    """Generate a realistic academic dataset with repeated rows per student."""
    if not isinstance(n_rows, int) or n_rows <= 0:
        raise ValueError("n_rows must be a positive integer.")
    rows_per_student = max(1, int(rows_per_student))
    rows_per_student = min(rows_per_student, 8)

    rng = np.random.default_rng(seed)
    departments = ["Computer Science", "Mathematics", "Biology", "Economics", "Psychology"]
    years = [1, 2, 3, 4]
    course_codes = ["CS101", "CS201", "MATH120", "BIO210", "ECON110", "PSY101", "CS310", "ENG200"]
    n_students = max(1, int(np.ceil(n_rows / rows_per_student)))
    records: list[dict[str, Any]] = []

    for student_idx in range(n_students):
        student_id = f"S-{student_idx + 1:04d}"
        gender = rng.choice(["Female", "Male", "Non-binary"], p=[0.52, 0.45, 0.03])
        age = int(rng.normal(20.5, 2.5))
        age = max(17, min(age, 35))
        department = rng.choice(departments)
        year = int(rng.choice(years))
        scholarship = bool(rng.random() < 0.22)
        base = 0.55 + (department == "Computer Science") * 0.11
        for _ in range(rows_per_student):
            course_code = rng.choice(course_codes)
            attendance = float(np.clip(rng.normal(82, 12), 40, 100))
            study_hours = float(np.clip(rng.normal(8.5 + (year * 1.0), 3.5), 1, 30))
            assignment_avg = float(np.clip(45 + attendance * 0.35 + study_hours * 2.2 + rng.normal(0, 8), 0, 100))
            midterm = float(np.clip(40 + attendance * 0.38 + rng.normal(0, 10), 0, 100))
            final_exam = float(np.clip(42 + attendance * 0.33 + study_hours * 1.4 + rng.normal(0, 12), 0, 100))
            score_signal = 0.35 * assignment_avg + 0.3 * midterm + 0.35 * final_exam
            if scholarship:
                score_signal += 4.0
            gpa = float(np.clip(score_signal / 100.0 * 4.0 + rng.normal(0, 0.25), 0.0, 4.0))
            final_grade_value = max(0.0, min(100.0, score_signal))
            if final_grade_value >= 90:
                final_grade = "A"
            elif final_grade_value >= 80:
                final_grade = "B"
            elif final_grade_value >= 70:
                final_grade = "C"
            elif final_grade_value >= 60:
                final_grade = "D"
            else:
                final_grade = "F"
            pass_fail = final_grade in {"A", "B", "C", "D"}
            records.append({
                "student_id": student_id,
                "gender": gender,
                "age": age,
                "department": department,
                "year_of_study": year,
                "course_code": course_code,
                "attendance_pct": round(attendance, 2),
                "study_hours_week": round(study_hours, 2),
                "assignment_avg": round(assignment_avg, 2),
                "midterm": round(midterm, 2),
                "final_exam": round(final_exam, 2),
                "gpa": round(gpa, 3),
                "scholarship": scholarship,
                "final_grade": final_grade,
                "pass_fail": pass_fail,
            })
            if len(records) >= n_rows:
                break
        if len(records) >= n_rows:
            break

    return pd.DataFrame(records[:n_rows])


def simulate(schema: list[dict[str, Any]], n_rows: int, seed: int | None = None, rows_per_student: int = 1) -> pd.DataFrame:
    """Generate a synthetic pandas DataFrame from a column schema.

    Args:
        schema: A list of column definitions with keys: name, type, params, and optional missing_pct.
        n_rows: Number of rows to create.
        seed: Random seed for reproducible generation.
        rows_per_student: Number of rows to emit per student when a student_id column is present.

    Returns:
        A pandas DataFrame containing the generated synthetic dataset.
    """
    if not isinstance(schema, list) or not schema:
        raise ValueError("Schema must be a non-empty list of columns.")
    if not isinstance(n_rows, int) or n_rows <= 0:
        raise ValueError("n_rows must be a positive integer.")
    if n_rows > 100_000:
        raise ValueError("n_rows cannot exceed 100,000.")

    if any(str(column.get("name", "")).lower() == "student_id" for column in schema):
        student_cols = [column for column in schema if str(column.get("name", "")).lower() == "student_id"]
        if student_cols and rows_per_student > 1:
            return simulate_academic_records(n_rows=n_rows, rows_per_student=rows_per_student, seed=seed)

    rng = np.random.default_rng(seed)
    fake = Faker()
    if seed is not None:
        fake.seed_instance(seed)

    columns: dict[str, pd.Series] = {}
    for index, column in enumerate(schema):
        if not isinstance(column, dict):
            raise ValueError(f"Column definition at index {index} must be a dictionary.")

        name = str(column.get("name", "")).strip()
        if not name:
            raise ValueError(f"Column definition at index {index} is missing a name.")

        dtype = str(column.get("type", "")).strip().lower()
        if dtype not in SUPPORTED_TYPES:
            raise ValueError(f"Unsupported column type '{dtype}' for column '{name}'.")

        params = column.get("params") or {}
        if not isinstance(params, dict):
            raise ValueError(f"Column '{name}' params must be a dictionary.")

        missing_pct = _normalize_missing_pct(column)

        if dtype in {"name", "email", "phone", "address", "city", "country", "company", "job", "date", "datetime", "uuid", "text"}:
            series = _generate_faker_series(fake, dtype, n_rows, params)
        elif dtype == "integer":
            series = _generate_integer_series(rng, n_rows, params)
        elif dtype == "float":
            series = _generate_float_series(rng, n_rows, params)
        elif dtype == "categorical":
            series = _generate_categorical_series(rng, n_rows, params)
        elif dtype == "boolean":
            series = _generate_boolean_series(rng, n_rows, params)
        else:
            raise ValueError(f"Unhandled type: {dtype}")

        if missing_pct > 0:
            mask = rng.random(n_rows) < missing_pct
            series = series.copy()
            series.loc[mask] = np.nan

        columns[name] = series

    return pd.DataFrame(columns)
