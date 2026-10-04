#!/usr/bin/env python3
"""Build a transparent empirical screening-threshold table from audited frontiers.

The endpoint is intentionally price-free: an operator chooses a target
empirical service coverage and receives the corresponding lower-tail offer
quantile and mean shortfall energy.  The replay column is explicitly the
replay rate of the frontier schedules that define each sample, not a fresh AC
replay of the quantile offer.  This is a screening metric, not a probabilistic
guarantee for future events.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TARGET_COVERAGES = (0.90, 0.95, 0.99)
SERVICE_HOURS = 4.0


def run(policy_path: Path, out_dir: Path) -> dict:
    df = pd.read_csv(policy_path)
    df = df[df["baseline_feasible"].astype(int) == 1].copy()
    rows = []
    for (site, method), g in df.groupby(["site", "method"], sort=True):
        x = g["service_kw"].to_numpy(float)
        for cov in TARGET_COVERAGES:
            # The lower tail is the offer that is empirically met by cov of
            # baseline-feasible units.  This is descriptive, not a guarantee.
            offer = float(np.quantile(x, 1.0 - cov, method="linear"))
            met = x >= offer - 1e-9
            replay = g["replay_feasible"].to_numpy(int).astype(bool)
            rows.append({
                "site": site,
                "method": method,
                "target_empirical_coverage": cov,
                "offer_kw": offer,
                "frontier_coverage": float(np.mean(met)),
                "frontier_replay_coverage": float(np.mean(met & replay)),
                "mean_shortfall_kwh": float(np.mean(np.maximum(0.0, offer - x) * SERVICE_HOURS)),
                "n_units": int(len(x)),
            })
    out = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_dir / "safe_offer_metrics.csv", index=False)
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    labels = {"network_lp": "AC-bound LP", "fixed_recovery": "Fixed recovery", "myopic_recovery": "Myopic recovery"}
    for (site, method), g in out.groupby(["site", "method"], sort=True):
        if method in {"network_lp", "fixed_recovery", "myopic_recovery"}:
            ax.plot(g["target_empirical_coverage"], g["offer_kw"], marker="o", label=f"{site} {labels[method]}")
    ax.set_xlabel("Target empirical coverage")
    ax.set_ylabel("Screening threshold (kW)")
    ax.set_title("Descriptive empirical screening thresholds")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, ncol=2, frameon=False)
    fig.tight_layout()
    fig.savefig(out_dir / "safe_offer_frontier.png", dpi=220)
    fig.savefig(out_dir / "safe_offer_frontier.pdf")
    plt.close(fig)
    payload = {"status": "descriptive_safe_offer_metrics", "target_coverages": list(TARGET_COVERAGES),
               "service_hours": SERVICE_HOURS, "n_rows": int(len(out)),
               "shortfall_energy_unit": "kWh",
               "replay_definition": "frontier schedule replay rate among units at or above the quantile offer; the quantile offer itself is not freshly AC-replayed",
               "warning": "Empirical coverage over retained baseline-feasible units is not a future delivery guarantee."}
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", type=Path, default=ROOT / "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "results/safe_offer_metrics_strict_v4")
    args = ap.parse_args()
    print(json.dumps(run(args.policy, args.out_dir), indent=2))
