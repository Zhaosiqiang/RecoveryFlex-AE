#!/usr/bin/env python3
"""Build auditable, interval-resolved profile banks for RecoveryFlex.

The first pilot release reduced both public profile sources to daily scalar
factors.  This script keeps the measured interval trajectories.  Ausgrid
records are half-hour *energy* values, while the OPSD household release stores
cumulative kWh.  Both are converted to average kW on their native interval
before any aggregation or split is made.

Splits are deterministic within each calendar month: the earliest 60% of
dates are train, the next 20% calibration, and the latest 20% test.  Thus every
month contributes to the test set and no date is shared between splits.  The
split labels and random group assignment are written to the manifest before
the profile arrays are used by an experiment.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"
SEED = 20261003


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def month_split(dates: Iterable[pd.Timestamp]) -> np.ndarray:
    """Return train/calibration/test labels without looking at outcomes."""
    dates = pd.DatetimeIndex(sorted(pd.to_datetime(list(dates))))
    labels = np.empty(len(dates), dtype="U5")
    frame = pd.DataFrame({"date": dates})
    for _, idx in frame.groupby(frame.date.dt.to_period("M"), sort=True).groups.items():
        ii = np.asarray(list(idx), dtype=int)
        n = len(ii)
        n_train = max(1, int(np.floor(0.60 * n)))
        n_cal = max(1, int(np.floor(0.20 * n)))
        # Keep a non-empty test tail even in a short month.
        if n_train + n_cal >= n:
            n_cal = max(0, n - n_train - 1)
            n_train = max(1, n - n_cal - 1)
        labels[ii[:n_train]] = "train"
        labels[ii[n_train:n_train + n_cal]] = "cal"
        labels[ii[n_train + n_cal:]] = "test"
    return labels


def _time_columns(columns: Iterable[str]) -> list[str]:
    # The archive uses 0:30,...,23:30,0:00.  This is the source's chronological
    # meter order, so preserve it rather than sorting lexicographically.
    return [str(c) for c in columns if ":" in str(c)]


def build_ausgrid(seed: int = SEED) -> dict:
    """Build group-mean 48-point kW profiles from the Ausgrid half-hour file."""
    src = RAW / "ausgrid" / "Solar home 2010-2011.csv"
    raw = pd.read_csv(src, skiprows=[0])
    raw["date"] = pd.to_datetime(raw["date"], dayfirst=True, errors="coerce")
    raw["Customer"] = pd.to_numeric(raw["Customer"], errors="coerce").astype("Int64")
    tcols = _time_columns(raw.columns)
    if len(tcols) != 48:
        raise ValueError(f"Ausgrid expected 48 half-hour columns, found {len(tcols)}")
    for c in tcols:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    # GC and CL are consumption energy per half-hour; GG is gross PV energy.
    # Customers without a CL meter have no CL row, which is an observed zero
    # controlled-load channel rather than a missing GC measurement.
    grouped = (raw[raw["Consumption Category"].isin(["GC", "CL", "GG"])]
               .groupby(["Customer", "date", "Consumption Category"], sort=True)[tcols]
               .mean())
    idx = grouped.index
    customers = np.array(sorted(raw["Customer"].dropna().astype(int).unique()), dtype=int)
    dates = pd.DatetimeIndex(sorted(raw["date"].dropna().unique()))
    arrays: dict[str, pd.DataFrame] = {}
    for cat in ("GC", "CL", "GG"):
        if cat in idx.get_level_values("Consumption Category"):
            arrays[cat] = grouped.xs(cat, level="Consumption Category")
        else:
            arrays[cat] = pd.DataFrame(index=pd.MultiIndex.from_product([customers, dates]), columns=tcols)
    base = pd.MultiIndex.from_product([customers, dates], names=["Customer", "date"])
    gc = arrays["GC"].reindex(base).fillna(0.0).to_numpy(float).reshape(len(customers), len(dates), 48)
    cl = arrays["CL"].reindex(base).fillna(0.0).to_numpy(float).reshape(len(customers), len(dates), 48)
    gg = arrays["GG"].reindex(base).fillna(0.0).to_numpy(float).reshape(len(customers), len(dates), 48)
    # A customer-day is valid only when the actual GC and GG rows have all 48
    # values.  Missing CL rows remain zero as documented above.
    gc_present = arrays["GC"].reindex(base).notna().all(axis=1).to_numpy().reshape(len(customers), len(dates))
    gg_present = arrays["GG"].reindex(base).notna().all(axis=1).to_numpy().reshape(len(customers), len(dates))
    valid = gc_present & gg_present
    rng = np.random.default_rng(seed)
    perm = rng.permutation(len(customers))
    # Ten fixed groups of equal size; the mapping is saved so every rerun is
    # exactly reproducible and no outcome is used to select a group.
    groups = np.array_split(perm, 10)
    load = (gc + cl) / 0.5  # kWh per 30 min -> average kW
    pv = gg / 0.5
    out_load, out_pv, out_dates = [], [], []
    for j, date in enumerate(dates):
        if not valid[:, j].all():
            continue
        out_load.append(np.stack([load[g, j].mean(axis=0) for g in groups]))
        out_pv.append(np.stack([pv[g, j].mean(axis=0) for g in groups]))
        out_dates.append(date
                        .tz_localize(None) if getattr(date, "tzinfo", None) else date)
    out_load = np.asarray(out_load, dtype=float)
    out_pv = np.asarray(out_pv, dtype=float)
    out_dates = pd.DatetimeIndex(out_dates)
    splits = month_split(out_dates)
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(OUT / "ausgrid_profile_bank_v2.npz", load_kw=out_load,
                        pv_kw=out_pv, dates=np.asarray(out_dates.strftime("%Y-%m-%d"), dtype="U10"),
                        split=np.asarray(splits, dtype="U5"),
                        group_ids=np.asarray(["-".join(map(str, customers[g])) for g in groups], dtype="U120"))
    pd.DataFrame({"date": out_dates.strftime("%Y-%m-%d"), "split": splits}).to_csv(
        OUT / "ausgrid_profile_bank_v2_index.csv", index=False)
    meta = {
        "source_file": str(src), "source_sha256": sha256(src), "seed": seed,
        "n_days": int(len(out_dates)), "n_customers": int(len(customers)),
        "n_groups": int(len(groups)), "intervals_per_day": 48,
        "units": "average kW; source values are kWh per 30-minute interval",
        "channels": "load = GC + CL (CL missing row treated as zero); pv = GG",
        "split_rule": "within each month: earliest 60% train, next 20% cal, latest 20% test",
        "split_counts": {k: int((splits == k).sum()) for k in ("train", "cal", "test")},
        "customer_group_mapping": [list(map(int, customers[g])) for g in groups],
    }
    (OUT / "ausgrid_profile_bank_v2_manifest.json").write_text(json.dumps(meta, indent=2))
    return meta


def build_opsd() -> dict:
    """Convert cumulative OPSD household channels into 15-minute kW profiles."""
    src = RAW / "opsd_household_15min.csv"
    load_col = "DE_KN_residential1_grid_import"
    pv_col = "DE_KN_residential1_pv"
    use = ["utc_timestamp", load_col, pv_col, "interpolated"]
    raw = pd.read_csv(src, usecols=use)
    raw["timestamp"] = pd.to_datetime(raw.pop("utc_timestamp"), utc=True)
    raw = raw.sort_values("timestamp").reset_index(drop=True)
    hours = raw["timestamp"].diff().dt.total_seconds() / 3600.0
    flags = raw["interpolated"].fillna("").astype(str)
    def interval_kw(col: str) -> pd.Series:
        cumulative = pd.to_numeric(raw[col], errors="coerce")
        delta = cumulative.diff()
        # Differences are energy over the actual elapsed interval.  Negative
        # deltas indicate a reset/bad segment and are excluded rather than
        # silently clipped.
        return delta.where(delta >= 0) / hours
    raw["load_kw"] = interval_kw(load_col)
    raw["pv_kw"] = interval_kw(pv_col)
    raw["load_interpolated"] = flags.str.contains(load_col, regex=False)
    raw["pv_interpolated"] = flags.str.contains(pv_col, regex=False)
    raw["date"] = raw.timestamp.dt.strftime("%Y-%m-%d")
    rows = []
    for date, g in raw.groupby("date", sort=True):
        g = g.sort_values("timestamp")
        if len(g) != 96 or g[["load_kw", "pv_kw"]].isna().any().any():
            continue
        if not np.allclose(g.timestamp.diff().dropna().dt.total_seconds().to_numpy(), 900.0):
            continue
        rows.append({"date": date, "load_kw": g.load_kw.to_numpy(float),
                     "pv_kw": g.pv_kw.to_numpy(float),
                     "load_interpolated_fraction": float(g.load_interpolated.mean()),
                     "pv_interpolated_fraction": float(g.pv_interpolated.mean())})
    rows = sorted(rows, key=lambda r: r["date"])
    dates = pd.DatetimeIndex([r["date"] for r in rows])
    splits = month_split(dates)
    load = np.stack([r["load_kw"] for r in rows]) if rows else np.empty((0, 96))
    pv = np.stack([r["pv_kw"] for r in rows]) if rows else np.empty((0, 96))
    interp = np.array([[r["load_interpolated_fraction"], r["pv_interpolated_fraction"]] for r in rows])
    np.savez_compressed(OUT / "opsd_profile_bank_v2.npz", load_kw=load, pv_kw=pv,
                        dates=np.asarray(dates.strftime("%Y-%m-%d"), dtype="U10"),
                        split=np.asarray(splits, dtype="U5"),
                        interpolation_fraction=interp)
    pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "split": splits,
                  "load_interpolated_fraction": interp[:, 0] if len(interp) else [],
                  "pv_interpolated_fraction": interp[:, 1] if len(interp) else []}).to_csv(
        OUT / "opsd_profile_bank_v2_index.csv", index=False)
    meta = {
        "source_file": str(src), "source_sha256": sha256(src),
        "n_days": int(len(dates)), "intervals_per_day": 96,
        "units": "average kW; cumulative kWh first-differenced over 15 minutes",
        "channels": {"load": load_col, "pv": pv_col},
        "interpolation_flag": "only the selected channel name in the semicolon-separated marker is counted",
        "split_rule": "within each month: earliest 60% train, next 20% cal, latest 20% test",
        "split_counts": {k: int((splits == k).sum()) for k in ("train", "cal", "test")},
    }
    (OUT / "opsd_profile_bank_v2_manifest.json").write_text(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    print(json.dumps({"ausgrid": build_ausgrid(), "opsd": build_opsd()}, indent=2))
