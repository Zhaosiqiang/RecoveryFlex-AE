#!/usr/bin/env python3
"""Plot the canonical declared-calendar recovery sensitivity table.

The figure is deliberately a rendering step only: it reads the point estimates
from ``date_cluster_summary.csv`` produced by the causal-policy sensitivity
run.  It does not rerun dispatch, AC checks, or bootstrap intervals.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IN = ROOT / "results" / "causal_capacity_sensitivity_strict_v4"
HORIZONS = ("causal_h4", "causal_h8", "causal_h12", "causal_h24")
HORIZON_LABELS = ("H4", "H8", "H12", "H24")
CAPACITIES = (250.0, 500.0, 1000.0, 2000.0)


def run(in_dir: Path = DEFAULT_IN, site: str = "634.1") -> None:
    summary_path = in_dir / "date_cluster_summary.csv"
    if not summary_path.is_file():
        raise FileNotFoundError(f"canonical summary is missing: {summary_path}")
    summary = pd.read_csv(summary_path)
    required = {"site", "energy_kwh", "method", "estimate"}
    missing = required - set(summary.columns)
    if missing:
        raise ValueError(f"canonical summary is missing columns: {sorted(missing)}")
    summary["site"] = summary["site"].astype(str)
    summary["method"] = summary["method"].astype(str)
    selected = summary[(summary["site"] == str(site)) & summary["method"].isin(HORIZONS)].copy()
    if selected.empty:
        raise ValueError(f"no declared-calendar rows found for site {site!r}")
    if selected.duplicated(["energy_kwh", "method"]).any():
        raise ValueError("canonical summary has duplicate site/energy/method rows")
    selected["energy_kwh"] = selected["energy_kwh"].astype(float)
    selected["estimate"] = selected["estimate"].astype(float)
    if not np.isfinite(selected[["energy_kwh", "estimate"]].to_numpy(float)).all():
        raise ValueError("canonical summary contains NaN or infinite heatmap values")
    energies = sorted(selected["energy_kwh"].unique())
    if energies != list(CAPACITIES):
        raise ValueError(f"expected capacities {list(CAPACITIES)}, got {energies}")
    matrix = selected.pivot(index="energy_kwh", columns="method", values="estimate").reindex(
        index=CAPACITIES, columns=HORIZONS
    )
    if matrix.isna().any().any():
        missing_cells = matrix.isna().stack()
        raise ValueError(f"canonical summary is incomplete for heatmap: {missing_cells[missing_cells].index.tolist()}")
    values = matrix.to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError("heatmap matrix contains NaN or infinite values")

    plt.rcParams.update({
        "font.size": 10,
        "axes.labelsize": 11,
        "axes.titlesize": 11,
        "xtick.labelsize": 10,
        "ytick.labelsize": 10,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    })
    fig, ax = plt.subplots(figsize=(7.4, 4.5), constrained_layout=True)
    im = ax.imshow(values, cmap="YlGnBu", aspect="auto", origin="upper",
                   vmin=float(values.min()), vmax=float(values.max()))
    ax.set_xticks(np.arange(len(HORIZONS)), HORIZON_LABELS)
    ax.set_yticks(np.arange(len(CAPACITIES)), ["250", "500", "1,000", "2,000"])
    ax.set_xlabel("Contract-information horizon (half-hour intervals)")
    ax.set_ylabel("Battery capacity (kWh)")
    ax.set_title(f"Finite-information recovery sensitivity at placement {site}")
    ax.set_xticks(np.arange(-.5, len(HORIZONS), 1), minor=True)
    ax.set_yticks(np.arange(-.5, len(CAPACITIES), 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.4)
    ax.tick_params(which="minor", bottom=False, left=False)
    midpoint = float((values.min() + values.max()) / 2.0)
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            color = "white" if values[i, j] > midpoint else "black"
            ax.text(j, i, f"{values[i, j]:.1f}", ha="center", va="center", color=color, fontsize=9)
    cbar = fig.colorbar(im, ax=ax, pad=0.03)
    cbar.set_label("Service power (kW)")
    fig.savefig(in_dir / "causal_horizon_heatmap.pdf", bbox_inches="tight")
    fig.savefig(in_dir / "causal_horizon_heatmap.png", dpi=220, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-dir", type=Path, default=DEFAULT_IN)
    parser.add_argument("--site", default="634.1")
    args = parser.parse_args()
    run(args.in_dir, args.site)
