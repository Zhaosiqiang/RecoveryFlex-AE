#!/usr/bin/env python3
"""Compute date-cluster summaries for the OPSD cross-source audit."""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "results/opsd_cross_source_strict_v5/policy_rows.csv"
DEFAULT_OUT = ROOT / "results/opsd_cross_source_strict_v5/date_cluster_summary.csv"


def summarize(policy_path: Path = DEFAULT_POLICY, out_path: Path = DEFAULT_OUT,
              reps: int = 5000, seed: int = 20261003) -> pd.DataFrame:
    frame = pd.read_csv(policy_path)
    frame["site"] = frame["site"].astype(str)
    frame = frame[frame["baseline_feasible"].astype(int).eq(1)].copy()
    rng = np.random.default_rng(seed)
    records: list[dict[str, object]] = []
    for (site, method), group in frame.groupby(["site", "method"], sort=True):
        date_means = group.groupby("date", sort=True)["service_kw"].mean().to_numpy(float)
        draws = rng.choice(date_means, size=(int(reps), len(date_means)), replace=True).mean(axis=1)
        records.append({
            "site": site,
            "method": method,
            "estimate_kw": float(date_means.mean()),
            "ci_low": float(np.quantile(draws, 0.025)),
            "ci_high": float(np.quantile(draws, 0.975)),
            "n_units": int(len(group)),
            "n_dates": int(len(date_means)),
            "bootstrap_reps": int(reps),
            "bootstrap_seed": int(seed),
        })
    out = pd.DataFrame(records)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--reps", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261003)
    args = parser.parse_args()
    print(summarize(args.policy, args.out, args.reps, args.seed).to_string(index=False))
