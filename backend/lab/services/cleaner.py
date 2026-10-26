"""Data cleaning utilities for preparing raw CSV datasets."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd


IDENTIFIER_HINTS = (
    "id",
    "uuid",
    "email",
    "phone",
    "mobile",
    "customer",
    "student",
    "employee",
    "account",
    "ssn",
    "passport",
    "tax",
    "document",
    "national",
    "serial",
    "record",
)


def _is_identifier_column(name: str, series: pd.Series) -> bool:
    lowered = str(name).lower()
    if any(hint in lowered for hint in IDENTIFIER_HINTS):
        return True
    if pd.api.types.is_string_dtype(series):
        non_null = series.dropna().astype(str)
        if non_null.empty:
            return False
        unique_ratio = non_null.nunique() / len(non_null)
        if unique_ratio > 0.95 and non_null.str.len().median() > 8:
            return True
    return False


def _coerce_numeric_strings(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        series = df[column]
        if (pd.api.types.is_numeric_dtype(series)
                and not pd.api.types.is_bool_dtype(series)):
            continue
        if not pd.api.types.is_object_dtype(series) and not pd.api.types.is_string_dtype(series):
            continue
        cleaned = series.astype(str).str.strip()
        numeric_candidates = pd.to_numeric(cleaned, errors="coerce")
        if numeric_candidates.notna().sum() / max(1, len(cleaned)) > 0.9:
            df[column] = numeric_candidates
    return df


def profile(df: pd.DataFrame) -> dict[str, Any]:
    """Return a metadata profile for the dataset columns."""
    rows = len(df)
    columns: dict[str, Any] = {}

    for column in df.columns:
        series = df[column]
        missing_count = int(series.isna().sum())
        missing_pct = round((missing_count / rows) * 100, 2) if rows else 0.0
        unique_count = int(series.nunique(dropna=True))

        column_summary: dict[str, Any] = {
            "dtype": str(series.dtype),
            "missing_count": missing_count,
            "missing_pct": missing_pct,
            "unique_count": unique_count,
            "is_identifier": bool(_is_identifier_column(str(column), series)),
        }

        # Boolean flags (for example scholarship/pass_fail) are categories,
        # even though pandas also classifies bool as numeric.
        if (pd.api.types.is_numeric_dtype(series)
                and not pd.api.types.is_bool_dtype(series)):
            numeric_series = pd.to_numeric(series, errors="coerce")
            column_summary["min"] = float(numeric_series.min()) if numeric_series.notna().any() else None
            column_summary["max"] = float(numeric_series.max()) if numeric_series.notna().any() else None
            column_summary["mean"] = float(numeric_series.mean()) if numeric_series.notna().any() else None
            column_summary["std"] = float(numeric_series.std()) if numeric_series.notna().any() else None
            column_summary["median"] = float(numeric_series.median()) if numeric_series.notna().any() else None
        else:
            top_values = series.dropna().astype(str).value_counts().head(5).to_dict()
            column_summary["top_values"] = top_values

        columns[str(column)] = column_summary

    return {
        "rows": rows,
        "columns": columns,
    }


def _apply_missing_policy(df: pd.DataFrame, options: dict[str, Any], report: dict[str, Any]) -> pd.DataFrame:
    default_policy = options.get("missing_numeric_policy", "mean")
    categorical_policy = options.get("missing_categorical_policy", "mode")

    for column in list(df.columns):
        series = df[column]
        if series.isna().sum() == 0:
            continue

        if (pd.api.types.is_numeric_dtype(series)
                and not pd.api.types.is_bool_dtype(series)):
            policy = options.get(f"{column}_missing_numeric_policy", default_policy)
            if policy == "drop":
                before = len(df)
                df = df[df[column].notna()].copy()
                report["changes"].append(f"Dropped {before - len(df)} rows with missing numeric values in '{column}'.")
                report["rows_removed"] += before - len(df)
                continue
            fill_value = series.mean() if policy == "mean" else series.median()
            df[column] = series.fillna(fill_value)
            report["changes"].append(f"Filled missing numeric values in '{column}' with {fill_value}.")
            report["imputed_values"][column] = {"fill_value": fill_value, "count": int(series.isna().sum())}
        else:
            policy = options.get(f"{column}_missing_categorical_policy", categorical_policy)
            if policy == "drop":
                before = len(df)
                df = df[df[column].notna()].copy()
                report["changes"].append(f"Dropped {before - len(df)} rows with missing categorical values in '{column}'.")
                report["rows_removed"] += before - len(df)
                continue
            fill_value = series.mode(dropna=True).iloc[0] if not series.mode(dropna=True).empty else "Unknown"
            if policy == "Unknown":
                fill_value = "Unknown"
            df[column] = series.fillna(fill_value)
            if isinstance(fill_value, str):
                df[column] = df[column].astype(str).str.strip()
            report["changes"].append(f"Filled missing categorical values in '{column}' with '{fill_value}'.")
            report["imputed_values"][column] = {"fill_value": fill_value, "count": int(series.isna().sum())}

    return df


def _apply_outliers(df: pd.DataFrame, strategy: str, report: dict[str, Any]) -> pd.DataFrame:
    if strategy == "none":
        return df

    for column in df.select_dtypes(include=[np.number]).columns:
        series = df[column]
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr

        if strategy == "clip":
            clipped = series.clip(lower=lower, upper=upper)
            if not clipped.equals(series):
                df[column] = clipped
                report["changes"].append(f"Clipped outliers in '{column}' to the IQR bounds.")
        elif strategy == "drop_rows":
            valid_mask = series.between(lower, upper)
            before = len(df)
            df = df[valid_mask].copy()
            removed = before - len(df)
            if removed:
                report["changes"].append(f"Dropped {removed} rows with outliers in '{column}' using the IQR rule.")
                report["rows_removed"] += removed
    return df


def _normalize_categories(df: pd.DataFrame) -> pd.DataFrame:
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            df[column] = series.map(lambda value: value.strip().lower() if isinstance(value, str) else value)
    return df


def _drop_missing_threshold_columns(df: pd.DataFrame, threshold: float, report: dict[str, Any]) -> pd.DataFrame:
    if threshold <= 0:
        return df
    dropped = []
    for column in list(df.columns):
        missing_ratio = df[column].isna().mean()
        if missing_ratio >= threshold:
            dropped.append(column)
    if dropped:
        report["columns_dropped"].extend(dropped)
        report["changes"].append(f"Dropped columns above missing threshold: {', '.join(dropped)}.")
        df = df.drop(columns=dropped)
    return df


def clean(df: pd.DataFrame, options: dict[str, Any] | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Clean a dataframe according to the provided options."""
    options = options or {}
    original = df.copy()
    cleaned = df.copy()
    report: dict[str, Any] = {
        "before_rows": len(cleaned),
        "after_rows": 0,
        "rows_removed": 0,
        "columns_dropped": [],
        "changes": [],
        "imputed_values": {},
        "missing_cells": 0,
        "privacy_unit_key": options.get("privacy_unit_key"),
    }

    if bool(options.get("drop_duplicate_rows", True)):
        before = len(cleaned)
        cleaned = cleaned.drop_duplicates().copy()
        removed = before - len(cleaned)
        if removed:
            report["changes"].append(f"Removed {removed} duplicate rows.")
            report["rows_removed"] += removed

    if bool(options.get("parse_dates", True)):
        for column in list(cleaned.columns):
            series = cleaned[column]
            if pd.api.types.is_numeric_dtype(series):
                continue
            try:
                parsed = pd.to_datetime(series, errors="coerce")
            except Exception:  # pragma: no cover - defensive fallback
                continue
            if parsed.notna().sum() / max(len(series), 1) > 0.8:
                cleaned[column] = parsed
                report["changes"].append(f"Parsed date-like values in '{column}'.")

    cleaned = _coerce_numeric_strings(cleaned)
    cleaned = cleaned.apply(lambda column: column.map(lambda value: value.strip() if isinstance(value, str) else value))

    if bool(options.get("normalize_category_case", True)):
        cleaned = _normalize_categories(cleaned)

    detected_identifiers = [
        col for col in cleaned.columns if _is_identifier_column(str(col), cleaned[col])
    ]
    identifier_columns = options.get("identifier_columns") or detected_identifiers
    privacy_unit_key = str(options.get("privacy_unit_key") or "").strip()
    if privacy_unit_key and privacy_unit_key in cleaned.columns:
        identifier_columns = [col for col in identifier_columns if col != privacy_unit_key]
        report["privacy_unit_key"] = privacy_unit_key

    if bool(options.get("drop_identifier_columns", True)):
        identifier_columns = [col for col in identifier_columns if col in cleaned.columns]
        if identifier_columns:
            cleaned = cleaned.drop(columns=identifier_columns)
            report["columns_dropped"].extend(identifier_columns)
            report["changes"].append(f"Dropped identifier columns: {', '.join(identifier_columns)}.")

    cleaned = _drop_missing_threshold_columns(
        cleaned,
        float(options.get("missing_threshold", 0.8)),
        report,
    )

    cleaned = _apply_missing_policy(cleaned, options, report)
    cleaned = _apply_outliers(cleaned, str(options.get("outlier_strategy", "none")), report)

    report["after_rows"] = len(cleaned)
    report["before_rows"] = len(original)
    report["rows_removed"] = max(report["rows_removed"], report["before_rows"] - report["after_rows"])
    return cleaned, report
