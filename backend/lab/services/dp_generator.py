"""Student-level differentially private tabular synthesis using a DP-GAN.

Privacy design
--------------
* Privacy unit: the student. Each student contributes at most
  ``policy.max_rows_per_student`` records (``build_student_table``).
* Only the **discriminator** ever touches real data. It is trained with DP-SGD
  (per-example gradient clipping + Gaussian noise, Poisson subsampling) and the
  privacy cost is tracked with an RDP accountant. The **generator** only sees
  the discriminator's gradients, so by post-processing it inherits the same
  guarantee, as does everything sampled from it afterwards.
* Numeric scaling uses *public* bounds only, never the data's min/max.
* Categorical domains are either public (``policy.public_categories``) or are
  released with a differentially private stability histogram, which spends a
  small slice of the (epsilon, delta) budget. Unseen/rare values map to
  ``__OTHER__``.
* Student-level guarantee for ``max_rows_per_student = k > 1`` is obtained from
  record-level DP-SGD via group privacy: eps_record = eps / k and
  delta_record = delta / (k * exp((k - 1) * eps_record)).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .cleaner import _is_identifier_column
from .privacy_definition import build_student_table, public_bounds_for_columns


# ---------------------------------------------------------------- settings --
# Each can be overridden with an attribute of the same lower-case name on the
# policy object (e.g. ``policy.gan_steps = 500``).
DEFAULT_STEPS = 1000            # discriminator/generator update rounds
DEFAULT_BATCH_SIZE = 128        # expected (Poisson) batch size
LATENT_DIM = 64
HIDDEN_DIM = 128
CLIP_NORM = 1.0                 # per-example gradient clipping bound
GENERATOR_LR = 2e-4
DISCRIMINATOR_LR = 2e-4
GUMBEL_TAU = 0.5
MAX_CATEGORIES = 50             # cap on one-hot width per categorical column
DOMAIN_EPSILON_PROPORTION = 0.10    # share of epsilon for category selection
DOMAIN_DELTA_PROPORTION = 0.10      # share of delta for category selection
OTHER = "__OTHER__"
MISSING = "__MISSING__"


# ----------------------------------------------------------------- helpers --
def _resolve_public_bound(column: str, bounds: dict[str, Any]) -> tuple[float, float]:
    """Find public (lower, upper) bounds for ``column`` or raise."""
    public_bound = bounds.get(column)
    if public_bound is None:
        public_bound = next(
            (value for name, value in bounds.items()
             if str(name).strip().casefold() == column.strip().casefold()),
            None,
        )
    if public_bound is None:
        public_bound = public_bounds_for_columns([column]).get(column)
    # Older saved policies use {"lower": ..., "upper": ...}.
    if isinstance(public_bound, dict):
        public_bound = (public_bound.get("lower"), public_bound.get("upper"))
    if not isinstance(public_bound, (list, tuple)) or len(public_bound) != 2:
        raise ValueError(f"Public lower and upper bounds are required for numeric column '{column}'.")
    lower, upper = float(public_bound[0]), float(public_bound[1])
    if not np.isfinite([lower, upper]).all() or lower >= upper:
        raise ValueError(f"Public bounds for '{column}' must be finite and lower than upper.")
    return lower, upper


def _select_categories(
    values: pd.Series, *, epsilon: float, delta: float, max_rows: int, rng: np.random.Generator,
) -> list[str]:
    """DP stability histogram: release only categories with a large noisy count.

    A student changes the count vector by at most ``max_rows`` in L1, so the
    noise scale is max_rows / epsilon. The threshold makes the chance that a
    category present only for a neighbouring dataset is released at most delta.
    """
    counts = values.value_counts()
    scale = max_rows / epsilon
    threshold = max_rows + scale * math.log(max_rows / (2.0 * delta))
    noisy = counts.to_numpy(dtype=float) + rng.laplace(0.0, scale, size=len(counts))
    order = np.argsort(-noisy)
    chosen = [str(counts.index[i]) for i in order if noisy[i] > threshold]
    return chosen[:MAX_CATEGORIES]


def _import_torch():
    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
        from torch.func import functional_call, grad, vmap
    except ImportError as exc:  # pragma: no cover - depends on runtime packaging
        raise RuntimeError("PyTorch (>=2.0) is required for GAN-based synthesis.") from exc
    try:
        from opacus.accountants import RDPAccountant
        from opacus.accountants.utils import get_noise_multiplier
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Opacus is required for privacy accounting of the DP-GAN.") from exc
    return torch, nn, F, functional_call, grad, vmap, RDPAccountant, get_noise_multiplier


def _activate(raw, layout, F, torch, *, tau: float = GUMBEL_TAU):
    """Map raw generator outputs to the encoded data space."""
    pieces, start = [], 0
    for kind, width in layout:
        seg = raw[:, start:start + width]
        start += width
        if kind == "num":
            pieces.append(torch.tanh(seg))
        elif kind == "mask":
            prob = torch.sigmoid(seg)
            hard = (torch.rand_like(prob) < prob).float()
            pieces.append(hard + prob - prob.detach())          # straight-through Bernoulli
        else:  # "cat"
            pieces.append(F.gumbel_softmax(seg, tau=tau, hard=True, dim=1))
    return torch.cat(pieces, dim=1)


# ------------------------------------------------------------------- main --
def generate_dp_synthetic(
    real_df: pd.DataFrame,
    *,
    policy: Any,
    n_rows: int,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Train a DP-GAN on one bounded record set per student and sample records.

    Numeric features are clipped and rescaled with public bounds. Categorical
    features are one-hot encoded over a public or DP-selected domain. The
    discriminator is trained with DP-SGD; the generator is trained only through
    the discriminator, so the released samples satisfy (epsilon, delta)
    student-level differential privacy.
    """
    if real_df.empty:
        raise ValueError("The cleaned source dataset is empty.")
    if n_rows < 1:
        raise ValueError("Output row count must be positive.")

    student_id_col = policy.student_id_col
    if student_id_col not in real_df.columns:
        raise ValueError(f"Student ID column '{student_id_col}' is missing.")
    if real_df[student_id_col].isna().any():
        raise ValueError("Every source row must have a student ID before private training.")

    max_rows = int(policy.max_rows_per_student)
    if max_rows < 1:
        raise ValueError("max_rows_per_student must be at least 1.")
    preserve_integer_columns = (
        {str(column) for column in real_df.columns
         if pd.api.types.is_integer_dtype(real_df[column].dtype)}
        if max_rows == 1 else set()
    )
    bool_columns = {str(column) for column in real_df.columns
                    if pd.api.types.is_bool_dtype(real_df[column].dtype)}
    students = int(real_df[student_id_col].nunique())
    if students < 2:
        raise ValueError("At least two distinct students are required for private synthesis.")

    student_records = build_student_table(real_df, {
        "student_id_col": student_id_col,
        "max_rows_per_student": policy.max_rows_per_student,
    })
    if student_records.empty:
        raise ValueError("No student records remain after applying the contribution bound.")

    columns = [str(column) for column in real_df.columns]
    bounds = {**public_bounds_for_columns(columns), **(policy.public_bounds or {})}
    features = student_records.drop(columns=[student_id_col], errors="ignore").copy()
    features = features[[column for column in features.columns
                         if not _is_identifier_column(str(column), features[column])
                         and not pd.api.types.is_datetime64_any_dtype(features[column])]]
    if features.empty:
        raise ValueError("No usable features remain after removing identifiers.")

    epsilon, delta = float(policy.epsilon), float(policy.delta)
    if epsilon <= 0 or not (0 < delta < 1):
        raise ValueError("epsilon must be positive and delta must be in (0, 1).")

    # ------------------------------------------------------ split features --
    numeric_cols: list[str] = []
    categorical_cols: list[str] = []
    for column in features.columns:
        series = features[column]
        if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
            numeric_cols.append(str(column))
        else:
            categorical_cols.append(str(column))

    numeric_bins: dict[str, tuple[float, float, bool]] = {}
    for column in numeric_cols:
        lower, upper = _resolve_public_bound(column, bounds)
        numeric_bins[column] = (lower, upper, column in preserve_integer_columns)

    public_categories = {str(k): [str(v) for v in vals]
                         for k, vals in (getattr(policy, "public_categories", None) or {}).items()}
    needs_dp_domain = [c for c in categorical_cols if c not in public_categories]

    # ----------------------------------------------------- privacy budgets --
    if needs_dp_domain:
        domain_epsilon = epsilon * DOMAIN_EPSILON_PROPORTION
        domain_delta = delta * DOMAIN_DELTA_PROPORTION
    else:
        domain_epsilon = domain_delta = 0.0
    train_epsilon = epsilon - domain_epsilon
    train_delta = delta - domain_delta
    # Group privacy: record-level DP-SGD -> student-level guarantee.
    record_epsilon = train_epsilon / max_rows
    record_delta = train_delta / (max_rows * math.exp((max_rows - 1) * record_epsilon))

    rng = np.random.default_rng(seed)

    # ------------------------------------------------ categorical domains --
    cat_values: dict[str, pd.Series] = {
        column: features[column].map(lambda v: MISSING if pd.isna(v) else str(v))
        for column in categorical_cols
    }
    domains: dict[str, list[str]] = {}
    for column in categorical_cols:
        if column in public_categories:
            chosen = list(dict.fromkeys(public_categories[column]))[:MAX_CATEGORIES]
        else:
            chosen = _select_categories(
                cat_values[column],
                epsilon=domain_epsilon / len(needs_dp_domain),
                delta=domain_delta / len(needs_dp_domain),
                max_rows=max_rows,
                rng=rng,
            )
        domains[column] = [c for c in chosen if c != OTHER] + [OTHER]

    # ------------------------------------------------------------ encoding --
    blocks: list[np.ndarray] = []
    layout: list[tuple[str, int]] = []
    if numeric_cols:
        values = np.zeros((len(features), len(numeric_cols)), dtype=np.float32)
        missing = np.zeros_like(values)
        for j, column in enumerate(numeric_cols):
            lower, upper, _ = numeric_bins[column]
            raw = pd.to_numeric(features[column], errors="coerce").to_numpy(dtype=float)
            is_missing = np.isnan(raw)
            clipped = np.clip(np.where(is_missing, (lower + upper) / 2.0, raw), lower, upper)
            values[:, j] = 2.0 * (clipped - lower) / (upper - lower) - 1.0
            missing[:, j] = is_missing
        blocks += [values, missing]
        layout += [("num", len(numeric_cols)), ("mask", len(numeric_cols))]
    for column in categorical_cols:
        index = {value: i for i, value in enumerate(domains[column])}
        onehot = np.zeros((len(features), len(domains[column])), dtype=np.float32)
        for row, value in enumerate(cat_values[column]):
            onehot[row, index.get(value, index[OTHER])] = 1.0
        blocks.append(onehot)
        layout.append(("cat", onehot.shape[1]))
    data = np.concatenate(blocks, axis=1)
    n_records, data_dim = data.shape
    if n_records < 2:
        raise ValueError("At least two records are required for private training.")

    # ------------------------------------------------------------- training --
    (torch, nn, F, functional_call, grad, vmap,
     RDPAccountant, get_noise_multiplier) = _import_torch()
    torch.manual_seed(seed)
    steps = int(getattr(policy, "gan_steps", DEFAULT_STEPS))
    batch_size = int(getattr(policy, "gan_batch_size", DEFAULT_BATCH_SIZE))
    if steps < 1 or batch_size < 2:
        raise ValueError("gan_steps must be >= 1 and gan_batch_size must be >= 2.")
    sample_rate = min(1.0, batch_size / n_records)
    expected_batch = sample_rate * n_records
    try:
        noise_multiplier = float(get_noise_multiplier(
            target_epsilon=record_epsilon, target_delta=record_delta,
            sample_rate=sample_rate, steps=steps, accountant="rdp",
        ))
    except ValueError as exc:
        raise ValueError(
            "The privacy budget is too small for this many training steps. "
            "Increase epsilon or reduce gan_steps."
        ) from exc
    accountant = RDPAccountant()
    accountant.history = [(noise_multiplier, sample_rate, steps)]
    spent_record_epsilon = float(accountant.get_epsilon(delta=record_delta))

    x_real = torch.from_numpy(data)
    generator = nn.Sequential(
        nn.Linear(LATENT_DIM, HIDDEN_DIM), nn.LeakyReLU(0.2),
        nn.Linear(HIDDEN_DIM, HIDDEN_DIM), nn.LeakyReLU(0.2),
        nn.Linear(HIDDEN_DIM, data_dim),
    )
    # No batch-norm / dropout in the discriminator: per-example gradients must
    # be independent of the other examples in the batch.
    discriminator = nn.Sequential(
        nn.Linear(data_dim, HIDDEN_DIM), nn.LeakyReLU(0.2),
        nn.Linear(HIDDEN_DIM, HIDDEN_DIM), nn.LeakyReLU(0.2),
        nn.Linear(HIDDEN_DIM, 1),
    )
    gen_opt = torch.optim.Adam(generator.parameters(), lr=GENERATOR_LR, betas=(0.5, 0.9))
    disc_opt = torch.optim.Adam(discriminator.parameters(), lr=DISCRIMINATOR_LR, betas=(0.5, 0.9))

    def real_loss(params, x):
        out = functional_call(discriminator, params, (x.unsqueeze(0),))
        return F.softplus(-out).sum()           # -log sigmoid(D(x))

    per_example_grad = vmap(grad(real_loss), in_dims=(None, 0))

    for _ in range(steps):
        # ---- discriminator step (the only one that touches real data) ----
        params = {name: p.detach() for name, p in discriminator.named_parameters()}
        keep = torch.rand(n_records) < sample_rate              # Poisson subsampling
        batch = x_real[keep]
        noisy_real = {name: torch.zeros_like(p) for name, p in params.items()}
        if len(batch) > 0:
            grads = per_example_grad(params, batch)
            norms = torch.sqrt(sum(g.flatten(1).pow(2).sum(1) for g in grads.values()))
            scale = (CLIP_NORM / (norms + 1e-6)).clamp(max=1.0)
            for name, g in grads.items():
                noisy_real[name] = (g * scale.view(-1, *([1] * (g.dim() - 1)))).sum(0)
        for name in noisy_real:
            noise = torch.randn_like(noisy_real[name]) * (noise_multiplier * CLIP_NORM)
            noisy_real[name] = (noisy_real[name] + noise) / expected_batch

        z = torch.randn(max(len(batch), batch_size), LATENT_DIM)
        with torch.no_grad():
            fake = _activate(generator(z), layout, F, torch)
        disc_opt.zero_grad()
        F.softplus(discriminator(fake)).mean().backward()       # no real data: no clipping
        for name, p in discriminator.named_parameters():
            p.grad = p.grad + noisy_real[name]
        disc_opt.step()

        # ---- generator step (post-processing of the discriminator) ----
        z = torch.randn(batch_size, LATENT_DIM)
        gen_opt.zero_grad()
        fake = _activate(generator(z), layout, F, torch)
        F.softplus(-discriminator(fake)).mean().backward()       # non-saturating loss
        gen_opt.step()

    # ------------------------------------------------------------- sampling --
    generator.eval()
    chunks = []
    with torch.no_grad():
        remaining = int(n_rows)
        while remaining > 0:
            size = min(remaining, 4096)
            chunks.append(_activate(generator(torch.randn(size, LATENT_DIM)), layout, F, torch).numpy())
            remaining -= size
    sampled = np.concatenate(chunks, axis=0)

    # ------------------------------------------------------------- decoding --
    synthetic = pd.DataFrame(index=range(int(n_rows)))
    start = 0
    n_num = len(numeric_cols)
    num_part = sampled[:, :n_num]
    mask_part = sampled[:, n_num:2 * n_num]
    start = 2 * n_num
    for j, column in enumerate(numeric_cols):
        lower, upper, is_integer = numeric_bins[column]
        decoded = np.clip(lower + (num_part[:, j] + 1.0) / 2.0 * (upper - lower), lower, upper)
        is_missing = mask_part[:, j] > 0.5
        if is_integer:
            int_lower, int_upper = int(np.ceil(lower)), int(np.floor(upper))
            if int_lower > int_upper:
                raise ValueError(f"Public bounds for integer column '{column}' contain no integers.")
            rounded = np.clip(np.rint(decoded), int_lower, int_upper)
            synthetic[column] = pd.array(
                [pd.NA if m else int(v) for v, m in zip(rounded, is_missing)], dtype="Int64")
        else:
            synthetic[column] = np.where(is_missing, np.nan, decoded.astype(np.float64))
    for column in categorical_cols:
        width = len(domains[column])
        labels = np.array(domains[column], dtype=object)[sampled[:, start:start + width].argmax(axis=1)]
        start += width
        out = pd.Series(labels, dtype=object).where(~pd.Series(labels).isin([OTHER, MISSING]), np.nan)
        if column in bool_columns:
            out = out.map({"True": True, "False": False})
        synthetic[column] = out

    synthetic = synthetic[[str(c) for c in features.columns]]
    return synthetic, {
        "method": "DP-GAN (GAN with DP-SGD discriminator)",
        "privacy_unit": "student",
        "student_id_column_excluded": student_id_col,
        "students_used": int(len(student_records)),
        "epsilon": epsilon,
        "delta": delta,
        "epsilon_domain_selection": domain_epsilon,
        "epsilon_training": train_epsilon,
        "delta_domain_selection": domain_delta,
        "delta_training": train_delta,
        "record_level_epsilon_target": record_epsilon,
        "record_level_epsilon_spent": spent_record_epsilon,
        "record_level_delta": record_delta,
        "noise_multiplier": noise_multiplier,
        "clip_norm": CLIP_NORM,
        "training_steps": steps,
        "sample_rate": sample_rate,
        "expected_batch_size": expected_batch,
        "latent_dim": LATENT_DIM,
        "hidden_dim": HIDDEN_DIM,
        "public_bounds_used": {column: [lower, upper]
                               for column, (lower, upper, _) in numeric_bins.items()},
        "integer_columns_preserved": [column for column, (_, _, is_integer) in numeric_bins.items()
                                      if is_integer],
        "categorical_domains": {column: domains[column] for column in categorical_cols},
        "categorical_domain_source": {
            column: ("public" if column in public_categories else "dp_selected")
            for column in categorical_cols},
    }