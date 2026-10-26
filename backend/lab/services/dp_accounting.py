from __future__ import annotations

from math import log
from typing import Any


class BudgetLedgerCapError(ValueError):
    """Raised when a DP operation would exceed the dataset budget cap."""


class BudgetLedger:
    """Small helper for enforcing a per-dataset privacy budget."""

    @staticmethod
    def enforce_cap(current_spent: float, cap: float, requested: float) -> None:
        if current_spent + requested > cap:
            raise BudgetLedgerCapError(
                f"DP budget cap would be exceeded: {current_spent + requested} > {cap}."
            )

    @staticmethod
    def projected_epsilon_curve(epsilon: float, epochs: int, per_epoch: float | None = None) -> list[float]:
        per_epoch = per_epoch if per_epoch is not None else epsilon / max(1, epochs)
        return [round(min(epsilon, (idx + 1) * per_epoch), 6) for idx in range(epochs)]


def estimate_delta(n_students: int, delta: float | None = None) -> float:
    """Validate delta against the standard DP recommendation of 1 / (10 * N)."""
    if n_students <= 0:
        raise ValueError("n_students must be positive.")
    if delta is None:
        delta = 1.0 / (10 * n_students)
    if delta <= 0:
        raise ValueError("delta must be positive.")
    if delta >= 1.0 / n_students:
        raise ValueError("delta must be less than 1 / n_students for a meaningful DP guarantee.")
    return float(delta)


def suggest_noise_multiplier(epsilon: float, delta: float, sample_rate: float, epochs: int) -> float:
    """Return a practical noise multiplier estimate when Opacus is unavailable."""
    if epsilon <= 0:
        raise ValueError("epsilon must be positive.")
    if delta <= 0:
        raise ValueError("delta must be positive.")
    if not 0 < sample_rate <= 1:
        raise ValueError("sample_rate must be between 0 and 1.")
    if epochs <= 0:
        raise ValueError("epochs must be positive.")
    estimate = (1.0 / epsilon) * (1.0 / max(sample_rate, 1e-6)) * (log(1.0 / delta) ** 0.5)
    return max(0.05, float(estimate / max(1.0, epochs ** 0.5)))


def epsilon_spent_curve(epsilon: float, epochs: int, delta: float = 1e-5) -> list[dict[str, Any]]:
    values = BudgetLedger.projected_epsilon_curve(epsilon, epochs)
    return [
        {"epoch": idx + 1, "epsilon": value, "delta": delta, "label": f"Epoch {idx + 1}"}
        for idx, value in enumerate(values)
    ]


def dp_presets() -> dict[str, dict[str, float | int | str]]:
    return {
        "Strong": {"epsilon": 1.0, "delta": 1e-6, "accountant": "rdp", "label": "Strong"},
        "Balanced": {"epsilon": 3.0, "delta": 1e-5, "accountant": "rdp", "label": "Balanced"},
        "Weak": {"epsilon": 10.0, "delta": 1e-5, "accountant": "prv", "label": "Weak"},
        "Custom": {"epsilon": 3.0, "delta": 1e-5, "accountant": "rdp", "label": "Custom"},
    }
