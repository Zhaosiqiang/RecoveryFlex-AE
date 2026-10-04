#!/usr/bin/env python3
"""Build the publication figure for the predeclared three-call grid."""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run(summary_path: Path, out_dir: Path) -> None:
    data = pd.read_csv(summary_path)
    gaps = [1.0, 2.0, 4.0, 6.0]
    capacities = [250.0, 500.0, 1000.0, 2000.0]
    # The contraction matrix is zero in nearly every cell, so its two dark
    # panels carry no visual information.  The one material residual is
    # reported in the Results text; the figure is reserved for the informative
    # exact-endpoint surfaces.
    fig, axes = plt.subplots(1, 2, figsize=(7.25, 3.15), constrained_layout=True)
    cmap_power = plt.get_cmap("viridis")
    power_matrices = []
    for site in (611.3, 634.1):
        subset = data[data.site == site]
        power_matrices.append(
            subset.pivot(index="capacity_kwh", columns="second_gap_h", values="lp_mean_kw")
            .reindex(index=capacities, columns=gaps).to_numpy()
        )
    power_min = float(np.nanmin(np.concatenate([m.ravel() for m in power_matrices])))
    power_max = float(np.nanmax(np.concatenate([m.ravel() for m in power_matrices])))
    last_power = None
    for col, site in enumerate((611.3, 634.1)):
        power = power_matrices[col]
        ax = axes[col]
        last_power = ax.imshow(power, aspect="auto", cmap=cmap_power, origin="upper",
                               vmin=power_min, vmax=power_max)
        ax.set_title(f"({chr(97 + col)}) Site {site}: exact endpoint")
        ax.set_xticks(range(len(gaps)), ["1", "2", "4", "6"])
        ax.set_yticks(range(len(capacities)), ["250", "500", "1000", "2000"])
        ax.set_xlabel("Gap before call 2 (h)")
        if col == 0:
            ax.set_ylabel("Battery capacity (kWh)")
        else:
            ax.set_yticklabels([])
        for i in range(power.shape[0]):
            for j in range(power.shape[1]):
                normalized = (power[i, j] - power_min) / max(power_max - power_min, 1e-9)
                ax.text(j, i, f"{power[i, j]:.1f}", ha="center", va="center",
                        color="white" if normalized < 0.48 else "black", fontsize=8)
    cbar1 = fig.colorbar(last_power, ax=axes, shrink=0.86, pad=0.025)
    cbar1.set_label("Exact scalar endpoint (kW)")
    fig.suptitle("Three-call chronological delivery stress with terminal SOC visible", fontsize=10.5)
    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / "three_call_chronology_grid.pdf", bbox_inches="tight")
    fig.savefig(out_dir / "three_call_chronology_grid.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path, default=ROOT / "results/three_call_grid_v1/three_call_summary.csv")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "paper/figures_v5")
    args = parser.parse_args()
    run(args.summary, args.out_dir)
