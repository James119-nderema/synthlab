"""Generation and fidelity services for synthetic data evaluation."""

from __future__ import annotations

from typing import Any

import pandas as pd

try:
    from sdv.metadata import Metadata
    from sdv.single_table import GaussianCopulaSynthesizer
    from sdmetrics.reports import QualityReport
except Exception:  # pragma: no cover - optional runtime dependency guard
    Metadata = None  # type: ignore[assignment]
    GaussianCopulaSynthesizer = None  # type: ignore[assignment]
    QualityReport = None  # type: ignore[assignment]


def _normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.copy()
    normalized.columns = [str(col).strip() for col in normalized.columns]
    return normalized


def generate_synthetic_dataset(real_df: pd.DataFrame, n_rows: int = 500, seed: int | None = 42) -> pd.DataFrame:
    """Generate a synthetic dataset using SDV if available; otherwise fallback to a deterministic sampling strategy."""
    if real_df.empty:
        raise ValueError("Real dataset cannot be empty.")

    if n_rows <= 0:
        raise ValueError("n_rows must be a positive integer.")

    df = _normalize_column_names(real_df)

    if Metadata is None or GaussianCopulaSynthesizer is None:
        synthetic = df.sample(n=n_rows, replace=True, random_state=seed).reset_index(drop=True)
        return synthetic

    metadata = Metadata.detect_from_dataframes({"table": df})
    synthesizer = GaussianCopulaSynthesizer(metadata=metadata)
    synthesizer.fit(data={"table": df})
    synthetic = synthesizer.sample(num_rows=n_rows)
    return _normalize_column_names(synthetic["table"] if isinstance(synthetic, dict) else synthetic).reset_index(drop=True)


def evaluate_fidelity(real_df: pd.DataFrame, synthetic_df: pd.DataFrame) -> dict[str, Any]:
    """Return a simple fidelity score and details for synthetic output."""
    if real_df.empty or synthetic_df.empty:
        return {"score": 0.0, "details": {"error": "Inputs cannot be empty."}}

    real = _normalize_column_names(real_df)
    synthetic = _normalize_column_names(synthetic_df)

    if list(real.columns) != list(synthetic.columns):
        common_cols = [col for col in real.columns if col in synthetic.columns]
        if not common_cols:
            return {"score": 0.0, "details": {"error": "No shared columns found."}}
        synthetic = synthetic[common_cols]
        real = real[common_cols]

    score = 1.0
    details: dict[str, Any] = {
        "rows": {"real": len(real), "synthetic": len(synthetic)},
        "columns": list(real.columns),
    }

    for column in real.columns:
        real_series = real[column]
        synth_series = synthetic[column]

        if pd.api.types.is_numeric_dtype(real_series) and pd.api.types.is_numeric_dtype(synth_series):
            real_values = pd.to_numeric(real_series, errors="coerce").replace([float("inf"), float("-inf")], pd.NA).dropna()
            synth_values = pd.to_numeric(synth_series, errors="coerce").replace([float("inf"), float("-inf")], pd.NA).dropna()
            real_mean = float(real_values.mean()) if not real_values.empty else None
            synth_mean = float(synth_values.mean()) if not synth_values.empty else None
            if real_mean is None or synth_mean is None:
                # An all-missing generated numeric column has no usable utility.
                mean_score = 0.0
            else:
                delta = abs(real_mean - synth_mean)
                mean_score = max(0.0, 1.0 - min(delta / max(abs(real_mean), 1.0), 1.0))
            score = min(score, mean_score)
            details[column] = {
                "mean_similarity": round(mean_score, 4),
                "real_mean": round(real_mean, 4) if real_mean is not None else None,
                "synthetic_mean": round(synth_mean, 4) if synth_mean is not None else None,
                "real_valid_rows": int(len(real_values)),
                "synthetic_valid_rows": int(len(synth_values)),
            }
        else:
            real_unique = set(real_series.dropna().astype(str).unique())
            synth_unique = set(synth_series.dropna().astype(str).unique())
            overlap = len(real_unique & synth_unique)
            total = max(len(real_unique | synth_unique), 1)
            category_score = overlap / total
            score = min(score, category_score)
            details[column] = {"category_overlap": round(category_score, 4)}

    score = max(0.0, min(1.0, float(score)))
    details["score"] = round(score, 4)
    return {"score": round(score, 4), "details": details}
