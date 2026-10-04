#!/usr/bin/env python3
"""Plot deterministic audited-headroom stress for the v5 manuscript."""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "results/headroom_margin_sensitivity_strict_v4/date_cluster_summary.csv"
OUT = ROOT / "paper/figures_v5"
SITES = ("611.3", "634.1")
METHODS = ("network_lp", "fixed_recovery", "myopic_recovery")
LABELS = {"network_lp": "AC-bound LP", "fixed_recovery": "Fixed recovery", "myopic_recovery": "Myopic recovery"}
COLORS = {"network_lp": "#0072B2", "fixed_recovery": "#D55E00", "myopic_recovery": "#009E73"}


def main() -> None:
    df = pd.read_csv(INPUT)
    df["site"] = df["site"].astype(str)
    df["margin_pct"] = 100.0 * df["margin"].astype(float)
    df = df[df["method"].isin(METHODS)].copy()
    if set(df["site"]) != set(SITES):
        raise ValueError("headroom figure input does not contain both audited placements")
    plt.rcParams.update({"font.size": 10, "axes.titlesize": 12, "axes.labelsize": 11,
                         "legend.fontsize": 9, "xtick.labelsize": 9, "ytick.labelsize": 10,
                         "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.5), sharey=True, constrained_layout=True)
    for ax, site in zip(axes, SITES):
        sub = df[df["site"] == site]
        for method in METHODS:
            p = sub[sub["method"] == method].sort_values("margin_pct")
            if len(p) != 4:
                raise ValueError(f"expected four margins for {site}/{method}")
            x = p["margin_pct"].to_numpy(float)
            y = p["estimate"].to_numpy(float)
            lo = p["ci_low"].to_numpy(float)
            hi = p["ci_high"].to_numpy(float)
            ax.plot(x, y, marker="o", linewidth=2.0, markersize=5,
                    color=COLORS[method], label=LABELS[method])
            ax.fill_between(x, lo, hi, color=COLORS[method], alpha=0.12, linewidth=0)
        ax.set_title(f"Battery placement {site}")
        ax.set_xlabel("Audited headroom margin (%)")
        ax.set_xticks([0, 5, 10, 20])
        ax.set_xlim(-0.8, 20.8)
        ax.grid(True, color="#d9d9d9", linewidth=0.7, alpha=0.75)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    axes[0].set_ylabel("Mean repeated service power (kW)")
    axes[1].legend(loc="upper right", frameon=False)
    fig.savefig(OUT / "headroom_margin_frontier.pdf", bbox_inches="tight")
    fig.savefig(OUT / "headroom_margin_frontier.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()
