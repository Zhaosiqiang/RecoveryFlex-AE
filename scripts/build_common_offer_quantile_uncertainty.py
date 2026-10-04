#!/usr/bin/env python3
"""Date-cluster uncertainty for the pooled common-offer calibration quantile."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run(policy: Path, out_dir: Path, *, seed: int = 20261003, n_boot: int = 5000) -> dict[str, float]:
    d = pd.read_csv(policy, dtype={"site": str})
    d["year"] = d["date"].astype(str).str[:4]
    cal = d[(d.method == "network_lp") & (d.year == "2012") & (d.baseline_feasible == 1)].copy()
    if len(cal) != 7203 or cal.date.nunique() != 103:
        raise ValueError(f"expected 7,203 units across 103 calibration dates, got {len(cal)} / {cal.date.nunique()}")
    values = cal.service_kw.to_numpy(float)
    point = float(np.quantile(values, 0.05, method="linear"))
    dates = np.array(sorted(cal.date.astype(str).unique()))
    by_date = {date: cal.loc[cal.date.astype(str).eq(date), "service_kw"].to_numpy(float) for date in dates}
    rng = np.random.default_rng(seed)
    boot = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        sampled_dates = rng.choice(dates, size=len(dates), replace=True)
        sample = np.concatenate([by_date[date] for date in sampled_dates])
        boot[i] = np.quantile(sample, 0.05, method="linear")
    quantiles = {"ci_low": float(np.quantile(boot, 0.025)), "median": float(np.quantile(boot, 0.5)), "ci_high": float(np.quantile(boot, 0.975))}
    date_means = np.array([by_date[date].mean() for date in dates])
    date_weighted = float(np.quantile(date_means, 0.05, method="linear"))
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"replicate": np.arange(n_boot), "calibration_p05_kw": boot}).to_csv(out_dir / "calibration_quantile_bootstrap.csv", index=False)
    summary = {
        "status": "common_offer_calibration_quantile_uncertainty_v1",
        "source": str(policy.relative_to(ROOT)),
        "method": "network_lp",
        "calibration_year": "2012",
        "n_units": int(len(cal)),
        "n_dates": int(len(dates)),
        "n_sites": int(cal.site.nunique()),
        "point_p05_kw": point,
        "date_cluster_bootstrap_seed": seed,
        "n_boot": n_boot,
        "date_cluster_bootstrap_95ci_kw": quantiles,
        "date_weighted_p05_kw": date_weighted,
        "estimand_note": "The production 79.453-kW offer is pooled and unit-weighted; the interval resamples retained dates as clusters while preserving all units within each selected date. The date-weighted lower-tail alternative is reported as a sensitivity, not substituted for the production rule.",
    }
    (out_dir / "calibration_quantile_bootstrap_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=ROOT / "results/location_sensitivity_external_2012_2013_strict_v4/policy_rows.csv")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/common_offer_temporal_evaluation_strict_v6")
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--n-boot", type=int, default=5000)
    args = parser.parse_args()
    print(json.dumps(run(args.policy, args.out_dir, seed=args.seed, n_boot=args.n_boot), indent=2))
