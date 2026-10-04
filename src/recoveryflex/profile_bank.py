"""Loader for the interval-resolved public profile banks.

The loader returns arrays in ``(day, interval, group)`` order and computes
normalization scales from train dates only.  Test-day amplitudes therefore
cannot change the scale used by a candidate model.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import numpy as np


@dataclass(frozen=True)
class ProfileBank:
    dates: np.ndarray
    split: np.ndarray
    load_kw: np.ndarray
    pv_kw: np.ndarray
    load_norm: np.ndarray
    pv_norm: np.ndarray
    train_load_scale_kw: np.ndarray
    train_pv_scale_kw: np.ndarray
    interpolation_fraction: np.ndarray | None = None


def load_bank(path: str | Path) -> ProfileBank:
    """Load an Ausgrid or OPSD v2 NPZ bank with train-only normalization."""
    x = np.load(path, allow_pickle=False)
    raw_load = np.asarray(x["load_kw"], dtype=float)
    raw_pv = np.asarray(x["pv_kw"], dtype=float)
    if raw_load.ndim == 3:  # Ausgrid: day, group, interval -> day, interval, group
        load = np.transpose(raw_load, (0, 2, 1))
        pv = np.transpose(raw_pv, (0, 2, 1))
    elif raw_load.ndim == 2:  # OPSD: day, interval -> one profile group
        load = raw_load[:, :, None]
        pv = raw_pv[:, :, None]
    else:
        raise ValueError(f"unexpected profile rank: {raw_load.ndim}")
    split = np.asarray(x["split"]).astype(str)
    train = split == "train"
    if not train.any():
        raise ValueError("profile bank has no train dates")
    load_scale = np.maximum(load[train].max(axis=(0, 1)), 1e-12)
    pv_scale = np.maximum(pv[train].max(axis=(0, 1)), 1e-12)
    interp = x["interpolation_fraction"] if "interpolation_fraction" in x.files else None
    return ProfileBank(np.asarray(x["dates"]).astype(str), split, load, pv,
                       load / load_scale[None, None, :],
                       pv / pv_scale[None, None, :], load_scale, pv_scale, interp)
