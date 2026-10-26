"""Privacy checks for synthetic data."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _prepare_encoded_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_bool_dtype(series):
            frame[column] = series.astype(int)
        elif pd.api.types.is_datetime64_any_dtype(series):
            frame[column] = series.astype(str)
    numeric_cols = [col for col in frame.columns if pd.api.types.is_numeric_dtype(frame[col])]
    categorical_cols = [col for col in frame.columns if col not in numeric_cols]

    for col in numeric_cols:
        frame[col] = pd.to_numeric(frame[col], errors="coerce").replace(
            [np.inf, -np.inf], np.nan,
        )
        # pandas delegates an all-NaN median to numpy.nanmedian, which emits
        # "Mean of empty slice". Use a neutral constant when a whole column
        # has no finite observations; otherwise impute with its finite median.
        observed = frame[col].dropna()
        median = float(observed.median()) if not observed.empty else 0.0
        frame[col] = frame[col].fillna(median)

    for col in categorical_cols:
        frame[col] = frame[col].fillna("Missing").astype(str)

    encoded = frame[numeric_cols].copy()
    if encoded.shape[1]:
        scaler = StandardScaler()
        encoded = pd.DataFrame(scaler.fit_transform(encoded), columns=encoded.columns, index=frame.index)

    if categorical_cols:
        dummies = pd.get_dummies(frame[categorical_cols], dummy_na=False)
        encoded = pd.concat([encoded, dummies], axis=1)

    if encoded.empty:
        encoded = pd.DataFrame(index=frame.index)
        for col in frame.columns:
            encoded[col] = frame[col].astype(str)

    return encoded.reset_index(drop=True)


def _nearest_distance_scores(real_df: pd.DataFrame, candidate_df: pd.DataFrame) -> dict[str, Any]:
    real_encoded = _prepare_encoded_frame(real_df)
    candidate_encoded = _prepare_encoded_frame(candidate_df)

    if not real_encoded.columns.equals(candidate_encoded.columns):
        common_cols = [col for col in real_encoded.columns if col in candidate_encoded.columns]
        if not common_cols:
            return {"distances": np.array([], dtype=float), "summary": {"min": 0.0, "p05": 0.0, "median": 0.0, "near_duplicates": 0, "exact_matches": 0}}
        real_encoded = real_encoded[common_cols]
        candidate_encoded = candidate_encoded[common_cols]

    if real_encoded.empty or candidate_encoded.empty:
        return {"distances": np.array([], dtype=float), "summary": {"min": 0.0, "p05": 0.0, "median": 0.0, "near_duplicates": 0, "exact_matches": 0}}

    nn = NearestNeighbors(n_neighbors=1, metric="euclidean")
    nn.fit(real_encoded.to_numpy())
    distances, _ = nn.kneighbors(candidate_encoded.to_numpy(), return_distance=True)
    distances = np.asarray(distances).reshape(-1)

    exact_matches = int(np.sum(distances <= 1e-8))
    threshold = 1e-3
    near_duplicates = int(np.sum(distances <= threshold))

    summary = {
        "min": float(np.min(distances)) if len(distances) else 0.0,
        "p05": float(np.quantile(distances, 0.05)) if len(distances) else 0.0,
        "median": float(np.median(distances)) if len(distances) else 0.0,
        "exact_matches": exact_matches,
        "near_duplicates": near_duplicates,
        "near_duplicate_threshold": threshold,
        "distances": distances,
    }
    return {"distances": distances, "summary": summary}


def _compute_exact_match_pct(real_df: pd.DataFrame, synthetic_df: pd.DataFrame) -> float:
    if real_df.empty or synthetic_df.empty:
        return 0.0
    real_rows = [tuple(row) for row in real_df.fillna("__NA__").itertuples(index=False, name=None)]
    synthetic_rows = [tuple(row) for row in synthetic_df.fillna("__NA__").itertuples(index=False, name=None)]
    exact_rows = set(real_rows) & set(synthetic_rows)
    return round((len(exact_rows) / max(len(synthetic_rows), 1)) * 100, 4)


def _risk_level_from_scores(aud: float, exact_match_pct: float, near_dup_pct: float) -> tuple[str, str, list[str]]:
    reasons: list[str] = []
    if aud > 0.6:
        reasons.append("Membership inference is above the typical safe range, suggesting a stronger re-identification signal.")
    elif aud > 0.55:
        reasons.append("Membership inference is moderately elevated and should be reviewed before release.")
    else:
        reasons.append("Membership inference remains close to random guessing, which is a reassuring baseline for privacy.")

    if exact_match_pct > 2:
        reasons.append("The synthetic data contains a meaningful share of exact matches to real rows, increasing disclosure risk.")
    if near_dup_pct > 0.2:
        reasons.append("Many synthetic rows are unusually close to real records, which can expose sensitive individuals.")
    if not reasons:
        reasons.append("No obvious disclosure signals were detected in the current check.")

    if aud > 0.6 or exact_match_pct > 2 or near_dup_pct > 0.2:
        level = "High"
    elif aud > 0.55 or exact_match_pct > 0.5 or near_dup_pct > 0.05:
        level = "Medium"
    else:
        level = "Low"

    if level == "High":
        recommendation = "Use a simpler generative model, increase the training sample size, or add differential privacy before publishing the synthetic data."
    elif level == "Medium":
        recommendation = "Tighten the privacy settings by reducing overfitting, removing direct identifiers, and re-running the privacy checks."
    else:
        recommendation = "The current synthetic data is relatively safe, but continue reviewing identifiers and monitor the release for drift."

    return level, recommendation, reasons


def run_privacy_check(real_df: pd.DataFrame, synthetic_df: pd.DataFrame, threshold: float = 1e-3) -> dict[str, Any]:
    """Run a privacy evaluation on a real vs synthetic dataset."""
    if real_df.empty or synthetic_df.empty:
        raise ValueError("Real and synthetic datasets must not be empty.")

    real = real_df.copy()
    synthetic = synthetic_df.copy()

    if list(real.columns) != list(synthetic.columns):
        shared = [col for col in real.columns if col in synthetic.columns]
        if not shared:
            raise ValueError("Real and synthetic datasets do not share any columns.")
        real = real[shared]
        synthetic = synthetic[shared]

    real_train, real_holdout = train_test_split(real, test_size=0.5, random_state=42)

    synthetic_to_real = _nearest_distance_scores(real, synthetic)
    baseline = _nearest_distance_scores(real_train, real_holdout)

    dcr = {
        "min": _safe_float(synthetic_to_real["summary"]["min"]),
        "p05": _safe_float(synthetic_to_real["summary"]["p05"]),
        "median": _safe_float(synthetic_to_real["summary"]["median"]),
        "exact_matches": int(synthetic_to_real["summary"]["exact_matches"]),
        "near_duplicates_count": int(synthetic_to_real["summary"]["near_duplicates"]),
        "threshold": float(threshold),
        "baseline": {
            "min": _safe_float(baseline["summary"]["min"]),
            "p05": _safe_float(baseline["summary"]["p05"]),
            "median": _safe_float(baseline["summary"]["median"]),
            "exact_matches": int(baseline["summary"]["exact_matches"]),
            "near_duplicates_count": int(baseline["summary"]["near_duplicates"]),
        },
    }

    exact_match_pct = _compute_exact_match_pct(real, synthetic)
    near_dup_pct = (dcr["near_duplicates_count"] / max(len(synthetic), 1)) * 100

    member_distances = _nearest_distance_scores(real_train, synthetic)["distances"]
    holdout_distances = _nearest_distance_scores(real_holdout, synthetic)["distances"]
    if len(member_distances) == 0 or len(holdout_distances) == 0:
        attack_auc = 0.5
    else:
        X = np.concatenate([member_distances.reshape(-1, 1), holdout_distances.reshape(-1, 1)])
        y = np.concatenate([
            np.ones(len(member_distances), dtype=int),
            np.zeros(len(holdout_distances), dtype=int),
        ])
        clf = RandomForestClassifier(n_estimators=200, random_state=42, max_depth=4)
        clf.fit(X, y)
        probabilities = clf.predict_proba(X)[:, 1]
        attack_auc = float(roc_auc_score(y, probabilities))

    risk_level, recommendation, reasons = _risk_level_from_scores(attack_auc, exact_match_pct, near_dup_pct)

    return {
        "risk_level": risk_level,
        "verdict": f"{risk_level} risk",
        "dcr": dcr,
        "membership_inference": {
            "attack_auc": round(float(attack_auc), 4),
            "interpretation": "About 0.5 is safe; above 0.6 is increasingly risky." if attack_auc <= 0.6 else "This is above the usual safe threshold and suggests a meaningful membership signal.",
        },
        "exact_match_pct": exact_match_pct,
        "recommendations": [recommendation],
        "reasons": reasons,
        "details": {
            "near_duplicate_pct": round(near_dup_pct, 4),
            "baseline_comparison": dcr["baseline"],
        },
    }
