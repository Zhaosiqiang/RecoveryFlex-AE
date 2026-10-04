"""Deterministic cluster-bootstrap primitives shared by result summaries.

The publication summaries use a date-cluster bootstrap.  A mutable RNG shared
by a loop makes an interval depend on which site, method, or outcome happened
to be processed before it.  This module derives an independent generator from
the declared base seed and a stable result context, and sorts cluster keys
before resampling.  Consequently the same data, seed, and context produce the
same interval regardless of input-row or outer-loop order.
"""
from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence

import numpy as np
import pandas as pd


def _stable_rng(seed: int, context: Sequence[object]) -> np.random.Generator:
    """Return a portable generator keyed by ``seed`` and ``context``.

    Python's built-in ``hash`` is intentionally process-randomized, so a
    cryptographic digest is used to make the stream stable across processes
    and machines.  The context is length-delimited through ``repr`` of a tuple
    and is only a stream key; it never changes the estimator itself.
    """
    if int(seed) != seed:
        raise ValueError("seed must be an integer")
    payload = repr((int(seed), tuple(str(item) for item in context))).encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    stream_seed = int.from_bytes(digest[:16], byteorder="little", signed=False)
    return np.random.default_rng(stream_seed)


def cluster_bootstrap(
    frame: pd.DataFrame,
    value: str,
    cluster_columns: Iterable[str],
    seed: int,
    n_boot: int,
    *,
    context: Sequence[object] = (),
    count_name: str = "n_clusters",
) -> dict[str, float | int]:
    """Estimate a mean and percentile interval by resampling cluster means.

    ``cluster_columns`` define the independent units (``("date",)`` for the
    primary interval or ``("date", "group")`` for the sensitivity interval).
    Cluster keys are sorted before aggregation.  The bootstrap stream is
    derived from ``seed`` and ``context`` rather than consumed from a shared
    mutable generator, so changing loop order cannot change an existing row.
    """
    columns = tuple(cluster_columns)
    if not columns:
        raise ValueError("at least one cluster column is required")
    missing = sorted((set(columns) | {value}) - set(frame.columns))
    if missing:
        raise ValueError(f"frame is missing bootstrap columns: {missing}")
    if count_name not in {"n_clusters", "n_dates"}:
        raise ValueError("count_name must be 'n_clusters' or 'n_dates'")
    empty = {
        "estimate": float("nan"),
        "ci_low": float("nan"),
        "ci_high": float("nan"),
        "prob_positive": float("nan"),
        "n_pairs": int(len(frame)),
        count_name: 0,
    }
    if frame.empty:
        return empty

    work = frame.loc[:, [*columns, value]].copy()
    work[value] = pd.to_numeric(work[value], errors="coerce")
    if work[value].isna().any() or not np.isfinite(work[value].to_numpy(float)).all():
        raise ValueError(f"bootstrap value {value!r} contains missing or non-finite data")
    # sort=True gives a canonical cluster order.  ``as_index`` also avoids
    # carrying a pandas index ordering into the random draw array.
    grouped = work.groupby(list(columns), sort=True, dropna=False, as_index=False)[value].mean()
    means = grouped[value].to_numpy(dtype=float, copy=True)
    if len(means) == 0:
        return empty | {count_name: 0}

    estimate = float(means.mean())
    if len(means) == 1 or int(n_boot) <= 1:
        samples = np.array([estimate], dtype=float)
    else:
        rng = _stable_rng(seed, tuple(context) + ("clusters", *columns))
        draws = rng.integers(0, len(means), size=(int(n_boot), len(means)))
        samples = means[draws].mean(axis=1)
    return {
        "estimate": estimate,
        "ci_low": float(np.quantile(samples, 0.025)),
        "ci_high": float(np.quantile(samples, 0.975)),
        "prob_positive": float(np.mean(samples > 0.0)),
        "n_pairs": int(len(frame)),
        count_name: int(len(means)),
    }

