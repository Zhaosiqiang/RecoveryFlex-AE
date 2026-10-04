#!/usr/bin/env python3
"""Build the publication figure for the predeclared three-call grid."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run(summary_path: Path, out_dir: Path) -> None:
    data = pd.read_csv(summary_path)
    gaps = [1.0, 2.0, 4.0, 6.0]
    capacities = [250.0, 500.0, 1000.0, 2000.0]
    # Keep the endpoint surfaces and show the mechanism in the same figure:
    # the lower row reports the aggregate-relaxation contraction, with the
    # active cumulative-window witness count called out in material cells.
    fig, axes = plt.subplots(2, 2, figsize=(7.25, 5.35), constrained_layout=True)
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
    contraction_matrices = []
    witness_matrices = []
    for site in (611.3, 634.1):
        subset = data[data.site == site]
        contraction_matrices.append(
            subset.pivot(index="capacity_kwh", columns="second_gap_h", values="contraction_mean_kw")
            .reindex(index=capacities, columns=gaps).to_numpy()
        )
        witness = subset.pivot(index="capacity_kwh", columns="second_gap_h", values="certificate_witness_counts")
        witness = witness.reindex(index=capacities, columns=gaps)
        counts = np.zeros((len(capacities), len(gaps)), dtype=int)
        for i in range(len(capacities)):
            for j in range(len(gaps)):
                value = witness.iloc[i, j]
                try:
                    counts[i, j] = int(sum(json.loads(value).values())) if value else 0
                except (TypeError, ValueError, json.JSONDecodeError):
                    counts[i, j] = 0
        witness_matrices.append(counts)
    contraction_max = float(np.nanmax(np.concatenate([m.ravel() for m in contraction_matrices])))
    last_power = None
    last_gap = None
    for col, site in enumerate((611.3, 634.1)):
        power = power_matrices[col]
        ax = axes[0, col]
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
        gap = contraction_matrices[col]
        gap_ax = axes[1, col]
        last_gap = gap_ax.imshow(gap, aspect="auto", cmap="magma", origin="upper",
                                 vmin=0.0, vmax=max(contraction_max, 1e-9))
        gap_ax.set_title(f"({chr(99 + col)}) Site {site}: contraction")
        gap_ax.set_xticks(range(len(gaps)), ["1", "2", "4", "6"])
        gap_ax.set_yticks(range(len(capacities)), ["250", "500", "1000", "2000"])
        gap_ax.set_xlabel("Gap before call 2 (h)")
        if col == 0:
            gap_ax.set_ylabel("Battery capacity (kWh)")
        else:
            gap_ax.set_yticklabels([])
        for i in range(gap.shape[0]):
            for j in range(gap.shape[1]):
                val = gap[i, j]
                label = f"{val:.1f}"
                norm = val / max(contraction_max, 1e-9)
                gap_ax.text(j, i, label, ha="center", va="center",
                            color="white" if norm < 0.52 else "black", fontsize=7)
                if val > 0.05:
                    gap_ax.add_patch(plt.Rectangle((j - 0.49, i - 0.49), 0.98, 0.98,
                                                   fill=False, edgecolor="cyan", linewidth=1.2))
                    gap_ax.text(j, i + 0.27, f"w={witness_matrices[col][i,j]:,}",
                                ha="center", va="center", color="white", fontsize=6.3)
        # The active cell carries the paired aggregate-relaxation and exact
        # values in a small callout so the figure shows the mechanism directly.
        if site == 634.1:
            i = capacities.index(500.0)
            j = gaps.index(6.0)
            row = data[(data.site == site) & (data.capacity_kwh == 500.0) & (data.second_gap_h == 6.0)].iloc[0]
            gap_ax.annotate(f"relax {row.relaxed_bound_mean_kw:.1f} → exact {row.lp_mean_kw:.1f} kW\nactive witness {witness_matrices[col][i,j]:,}",
                            xy=(j, i), xytext=(2.7, 2.7), textcoords="data",
                            arrowprops={"arrowstyle": "-", "color": "white", "lw": 0.8},
                            fontsize=6.2, color="white", ha="center",
                            bbox={"boxstyle": "round,pad=0.25", "fc": "#3b1f4a", "ec": "white", "alpha": 0.9})
    cbar1 = fig.colorbar(last_power, ax=axes[0, :], shrink=0.86, pad=0.025)
    cbar1.set_label("Exact scalar endpoint (kW)")
    cbar2 = fig.colorbar(last_gap, ax=axes[1, :], shrink=0.86, pad=0.025)
    cbar2.set_label("Aggregate relaxation − exact endpoint (kW)")
    fig.suptitle("Three-call chronology: exact endpoint and recovery-window contraction", fontsize=10.5)
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
