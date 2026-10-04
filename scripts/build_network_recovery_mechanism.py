#!/usr/bin/env python3
"""Relate the LP advantage to within-horizon AC recovery headroom variation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def run(results_dir: Path, out_dir: Path) -> dict:
    rows = pd.read_csv(results_dir / "policy_rows.csv")
    # Match the primary endpoint: mechanism summaries are conditional on the
    # independently audited zero-power baseline gate.
    rows = rows[rows.baseline_feasible == 1].copy()
    bounds = pd.read_csv(results_dir / "ac_bounds.csv")
    recovery = bounds[bounds.interval.between(12, 23) | bounds.interval.between(28, 47)].copy()
    headroom = recovery.groupby(["date", "group", "site"], as_index=False).agg(
        charge_mean_kw=("charge_limit_kw", "mean"),
        charge_min_kw=("charge_limit_kw", "min"),
        charge_max_kw=("charge_limit_kw", "max"),
        export_mean_kw=("export_limit_kw", "mean"),
    )
    headroom["charge_cv"] = np.where(
        headroom.charge_mean_kw > 0,
        (headroom.charge_max_kw - headroom.charge_min_kw) / headroom.charge_mean_kw,
        np.nan,
    )
    wide = rows.pivot(index=["date", "group", "site"], columns="method", values="service_kw").reset_index()
    wide["lp_minus_myopic_kw"] = wide["network_lp"] - wide["myopic_recovery"]
    wide["lp_minus_fixed_kw"] = wide["network_lp"] - wide["fixed_recovery"]
    merged = wide.merge(headroom, on=["date", "group", "site"], how="inner", validate="one_to_one")
    merged.to_csv(out_dir / "headroom_effects.csv", index=False)
    summary = []
    for site, frame in merged.groupby("site"):
        for effect in ("lp_minus_myopic_kw", "lp_minus_fixed_kw"):
            valid = frame[["charge_cv", effect]].dropna()
            summary.append({
                "site": str(site),
                "effect": effect,
                "n": int(len(valid)),
                "spearman_rho": float(valid.corr(method="spearman").iloc[0, 1]) if len(valid) > 1 else np.nan,
                "pearson_r": float(valid.corr(method="pearson").iloc[0, 1]) if len(valid) > 1 else np.nan,
                "mean_effect_kw": float(frame[effect].mean()),
                "mean_charge_cv": float(frame.charge_cv.mean()),
            })
    metadata = {
        "status": "network_recovery_mechanism_v2",
        "results_dir": str(results_dir.resolve()),
        "population": "baseline_feasible",
        "summary": summary,
    }
    (out_dir / "mechanism_summary.json").write_text(json.dumps(metadata, indent=2, allow_nan=True))
    return metadata


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print(json.dumps(run(args.results_dir, args.out_dir), indent=2, allow_nan=True))
