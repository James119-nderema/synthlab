from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


DEFAULT_PUBLIC_BOUNDS = {
    "gpa": [0.0, 4.0],
    "math_score": [0.0, 100.0],
    "science_score": [0.0, 100.0],
    "score": [0.0, 100.0],
    "test_score": [0.0, 100.0],
    "exam_score": [0.0, 100.0],
    "quiz_score": [0.0, 100.0],
    "midterm_score": [0.0, 100.0],
    "final_score": [0.0, 100.0],
    "attendance_pct": [0.0, 100.0],
    "attendance_rate": [0.0, 100.0],
    "fee_balance": [0.0, 50000.0],
    "study_hours_week": [0.0, 40.0],
    "assignment_avg": [0.0, 100.0],
    "midterm": [0.0, 100.0],
    "final_exam": [0.0, 100.0],
    "age": [15.0, 40.0],
    "year_of_study": [1.0, 8.0],
}


def public_bounds_for_columns(columns: list[str]) -> dict[str, list[float]]:
    """Return suggested public ranges for recognizable academic measures.

    These are domain limits, not ranges calculated from private observations.
    Unknown numeric columns remain unset and must be assigned an external bound.
    """
    suggestions: dict[str, list[float]] = {}
    for column in columns:
        name = str(column).strip()
        key = name.casefold()
        bound = next((value for known, value in DEFAULT_PUBLIC_BOUNDS.items()
                      if known.casefold() == key), None)
        if bound is None and (key.endswith("_score") or key.endswith("_grade")):
            bound = [0.0, 100.0]
        if bound is None and ("attendance" in key or key.endswith("_percent") or key.endswith("_pct")):
            bound = [0.0, 100.0]
        if bound is not None:
            suggestions[name] = list(bound)
    return suggestions


def build_student_table(df: pd.DataFrame, policy: dict[str, Any] | None = None) -> pd.DataFrame:
    """Return a student-level table that keeps one row per student by default."""
    if df.empty:
        return df.copy()

    policy = policy or {}
    student_id_col = str(policy.get("student_id_col") or "student_id")
    max_rows_per_student = int(policy.get("max_rows_per_student") or 1)
    if student_id_col not in df.columns:
        return df.copy()

    table = df.copy()
    if max_rows_per_student > 1:
        table = table.groupby(student_id_col, group_keys=False).head(max_rows_per_student).copy()

    numeric_cols = [
        col for col in table.columns
        if col != student_id_col
        and pd.api.types.is_numeric_dtype(table[col])
        and not pd.api.types.is_bool_dtype(table[col])
    ]
    categorical_cols = [col for col in table.columns if col != student_id_col and col not in numeric_cols]
    if not numeric_cols and not categorical_cols:
        return table[[student_id_col]].drop_duplicates().copy() if student_id_col in table.columns else table.copy()

    summary_rows = []
    for student_id, group in table.groupby(student_id_col, sort=False):
        row: dict[str, Any] = {student_id_col: student_id}
        for col in numeric_cols:
            values = group[col].dropna()
            row[col] = float(values.mean()) if not values.empty else 0.0
        for col in categorical_cols:
            values = group[col].dropna()
            row[col] = values.mode().iloc[0] if not values.empty else None
        summary_rows.append(row)

    return pd.DataFrame(summary_rows)


def group_split_by_student(df: pd.DataFrame, student_id_col: str = "student_id", test_size: float = 0.2, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split a dataset by student so no student appears in both train and test."""
    if student_id_col not in df.columns:
        raise ValueError(f"Column '{student_id_col}' not found for student-level split.")
    unique_students = pd.Series(df[student_id_col].dropna().unique())
    rng = np.random.default_rng(seed)
    shuffled = unique_students.iloc[rng.permutation(len(unique_students))].reset_index(drop=True)
    split_point = max(1, int(len(shuffled) * (1.0 - test_size)))
    train_students = set(shuffled.iloc[:split_point].tolist())
    test_students = set(shuffled.iloc[split_point:].tolist())
    train_df = df[df[student_id_col].isin(train_students)].copy()
    test_df = df[df[student_id_col].isin(test_students)].copy()
    return train_df, test_df


def risk_scan(df: pd.DataFrame, policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sum up privacy risks for a student-level dataset."""
    policy = policy or {}
    student_id_col = str(policy.get("student_id_col") or "student_id")
    quasi_identifiers = list(policy.get("quasi_identifiers") or [])
    sensitive_attributes = list(policy.get("sensitive_attributes") or [])

    if not quasi_identifiers and student_id_col in df.columns:
        quasi_identifiers = ["department", "year_of_study", "gender", "age"]

    result: dict[str, Any] = {
        "n_students": int(df[student_id_col].nunique()) if student_id_col in df.columns else int(len(df)),
        "n_rows": int(len(df)),
        "k_anonymity": {},
        "small_cells": [],
        "sensitive_attributes": sensitive_attributes,
        "summary": "No obvious small-group risk detected.",
    }

    if quasi_identifiers:
        key_cols = [col for col in quasi_identifiers if col in df.columns]
        if key_cols:
            grouped = df.groupby(key_cols, dropna=False).size().reset_index(name="count")
            small_cells = grouped[grouped["count"] < 5]
            result["small_cells"] = small_cells.to_dict(orient="records")
            result["k_anonymity"]["minimum_group_size"] = int(grouped["count"].min()) if not grouped.empty else 0
            result["k_anonymity"]["small_cell_count"] = int(len(small_cells))
            if len(small_cells):
                result["summary"] = "Some quasi-identifier cells are smaller than 5 records; review and tighten the policy before release."

    if result["n_students"] and result["n_rows"]:
        ratio = result["n_rows"] / max(result["n_students"], 1)
        result["rows_per_student"] = round(float(ratio), 2)

    return result
