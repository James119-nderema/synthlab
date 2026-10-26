"""Post-hoc utility evaluation for DP synthetic academic data."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .cleaner import _is_identifier_column
from .generator import evaluate_fidelity


def _tstr_evaluate(
    real: pd.DataFrame, synthetic: pd.DataFrame, target: str, seed: int = 42,
) -> tuple[float | None, dict[str, Any]]:
    """Train a small linear regressor and report missing-feature imputation."""
    if target not in real.columns or target not in synthetic.columns:
        raise ValueError(f"Target column '{target}' must exist in both datasets.")
    real_target = pd.to_numeric(real[target], errors="coerce")
    synthetic_target = pd.to_numeric(synthetic[target], errors="coerce")
    real_valid = real_target.notna()
    synthetic_valid = synthetic_target.notna()
    real = real.loc[real_valid].reset_index(drop=True)
    real_target = real_target.loc[real_valid].reset_index(drop=True)
    synthetic = synthetic.loc[synthetic_valid].reset_index(drop=True)
    synthetic_target = synthetic_target.loc[synthetic_valid].reset_index(drop=True)
    target_counts = {
        "real_target_records": int(len(real_target)),
        "synthetic_target_records": int(len(synthetic_target)),
    }
    if len(real) < 3 or len(synthetic) < 2:
        return None, {
            **target_counts,
            "training_rows": int(len(synthetic)),
            "features": 0,
            "missing_training_values": 0,
            "all_missing_features": [],
            "status": "insufficient target records for TSTR",
        }

    columns = [column for column in real.columns if column in synthetic.columns and column != target]
    columns = [column for column in columns
               if not _is_identifier_column(str(column), real[column])
               and not _is_identifier_column(str(column), synthetic[column])]
    if columns:
        rng = np.random.default_rng(seed)
        order = rng.permutation(len(real))
        test_count = max(1, min(len(real) - 1, int(round(len(real) * 0.2))))
        test_idx = order[:test_count]
        test_features = real.iloc[test_idx][columns].reset_index(drop=True)
        combined = pd.concat([synthetic[columns], test_features], ignore_index=True)
        encoded = pd.get_dummies(combined, dummy_na=True, dtype=float)
        train_x = encoded.iloc[:len(synthetic)].to_numpy(dtype=float)
        test_x = encoded.iloc[len(synthetic):].to_numpy(dtype=float)
        missing_per_feature = np.isnan(train_x).sum(axis=0)
        all_missing = [str(encoded.columns[idx]) for idx, count in enumerate(missing_per_feature)
                       if count == len(train_x)]
        diagnostics = {
            **target_counts,
            "training_rows": int(len(train_x)),
            "features": int(train_x.shape[1]),
            "missing_training_values": int(missing_per_feature.sum()),
            "all_missing_features": all_missing,
            "status": "ok",
        }
        medians = np.zeros(train_x.shape[1], dtype=float)
        for idx in range(train_x.shape[1]):
            finite_values = train_x[np.isfinite(train_x[:, idx]), idx]
            if finite_values.size:
                medians[idx] = float(np.median(finite_values))
        train_x = np.where(np.isfinite(train_x), train_x, medians)
        test_x = np.where(np.isfinite(test_x), test_x, medians)
        means = train_x.mean(axis=0)
        scales = train_x.std(axis=0)
        scales[scales == 0] = 1.0
        train_x = (train_x - means) / scales
        test_x = (test_x - means) / scales
    else:
        rng = np.random.default_rng(seed)
        order = rng.permutation(len(real))
        test_count = max(1, min(len(real) - 1, int(round(len(real) * 0.2))))
        test_idx = order[:test_count]
        train_x = np.empty((len(synthetic), 0), dtype=float)
        test_x = np.empty((test_count, 0), dtype=float)
        diagnostics = {
            **target_counts,
            "training_rows": int(len(train_x)), "features": 0,
            "missing_training_values": 0, "all_missing_features": [], "status": "ok",
        }

    test_y = real_target.iloc[test_idx].to_numpy(dtype=float)
    train_y = synthetic_target.to_numpy(dtype=float)
    design_train = np.column_stack([np.ones(len(train_y)), train_x])
    design_test = np.column_stack([np.ones(len(test_y)), test_x])
    coefficients, *_ = np.linalg.lstsq(design_train, train_y, rcond=None)
    predictions = design_test @ coefficients
    total = float(np.sum((test_y - test_y.mean()) ** 2))
    if total <= 1e-12:
        return None, diagnostics
    residual = float(np.sum((test_y - predictions) ** 2))
    return float(1.0 - residual / total), diagnostics


def _tstr_r2(real: pd.DataFrame, synthetic: pd.DataFrame, target: str, seed: int = 42) -> float | None:
    """Train a small linear regressor on synthetic data and score on held-out real rows."""
    return _tstr_evaluate(real, synthetic, target, seed)[0]


def evaluate_utility(real: pd.DataFrame, synthetic: pd.DataFrame, target: str) -> dict[str, Any]:
    """Return fidelity, a real holdout baseline, and train-synthetic-test-real R²."""
    if real.empty or synthetic.empty:
        raise ValueError("The real and synthetic datasets must both contain records.")
    if len(real) < 3:
        raise ValueError("At least 3 real source records are required for a held-out utility baseline.")
    fidelity = evaluate_fidelity(real, synthetic)
    if "error" in fidelity["details"]:
        raise ValueError(fidelity["details"]["error"])

    shared = [column for column in real.columns if column in synthetic.columns]
    if target not in shared:
        raise ValueError(f"Target column '{target}' is not shared by the source and synthetic datasets.")
    real_shared = real[shared].reset_index(drop=True)
    synthetic_shared = synthetic[shared].reset_index(drop=True)
    rng = np.random.default_rng(42)
    order = rng.permutation(len(real_shared))
    split = max(1, min(len(real_shared) - 1, int(round(len(real_shared) * 0.8))))
    baseline = evaluate_fidelity(real_shared.iloc[order[:split]], real_shared.iloc[order[split:]])
    baseline_score = float(baseline["score"])
    score = float(fidelity["score"])
    tstr_r2, tstr_diagnostics = _tstr_evaluate(real_shared, synthetic_shared, target)
    return {
        "utility_score": score,
        "baseline_score": baseline_score,
        "utility_vs_baseline": round(score - baseline_score, 4),
        "tstr_r2": tstr_r2,
        "tstr_diagnostics": tstr_diagnostics,
        "target": target,
        "fidelity_details": fidelity["details"],
        "rows": {"real": len(real), "synthetic": len(synthetic)},
    }
