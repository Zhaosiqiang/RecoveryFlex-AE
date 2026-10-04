#!/usr/bin/env python3
"""Build compact, journal-ready figures for the network-recovery audit.

The figure builder is read-only with respect to experiment outputs. The
frontier uses date-cluster bootstrap intervals when the statistics directory
is present and falls back to a descriptive mean for an older smoke directory.
It never creates a statistical result itself.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "results" / "network_recovery_external_2012_2013_strict_v4"
DEFAULT_TRACE = DEFAULT_RESULTS
DEFAULT_OUT = ROOT / "figures" / "network_recovery_strict_v4"

# Restrained, colour-blind-safe colours that remain legible in grayscale.
COLORS = {
    "network_lp": "#0072B2",
    "fixed_recovery": "#D55E00",
    "myopic_recovery": "#CC79A7",
    "energy_only": "#666666",
}
LABELS = {
    "network_lp": "AC-bound LP",
    "fixed_recovery": "Fixed recovery",
    "myopic_recovery": "Myopic recovery",
    "energy_only": "Constant-bound counterfactual",
}
METHODS = ("network_lp", "fixed_recovery", "myopic_recovery", "energy_only")

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 9,
    "axes.titlesize": 10,
    "axes.labelsize": 9,
    "legend.fontsize": 8,
    "figure.dpi": 140,
    "savefig.dpi": 320,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.8,
    "xtick.major.width": 0.8,
    "ytick.major.width": 0.8,
})


def _save(fig: plt.Figure, out: Path, stem: str, *, rect=None) -> None:
    fig.tight_layout(rect=rect)
    fig.savefig(out / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(out / f"{stem}.png", bbox_inches="tight", dpi=320)
    plt.close(fig)


def _policy(path: Path) -> pd.DataFrame:
    d = pd.read_csv(path / "policy_rows.csv")
    required = {"site", "method", "service_kw", "replay_feasible", "baseline_feasible"}
    missing = required - set(d.columns)
    if missing:
        raise ValueError(f"{path}/policy_rows.csv is missing {sorted(missing)}")
    return d


def _frontier_data(results: Path) -> pd.DataFrame:
    stats = results / "statistics" / "method_summary.csv"
    if stats.exists():
        d = pd.read_csv(stats)
        d = d[(d.population == "baseline_feasible") & (d.outcome == "service_kw") & (d.cluster_level == "date")].copy()
        d["mean_service_kw"] = d["estimate"]
        d["lower"] = d["ci_low"]
        d["upper"] = d["ci_high"]
        return d[["site", "method", "mean_service_kw", "lower", "upper"]]
    d = _policy(results)
    d = d[d.baseline_feasible == 1]
    g = d.groupby(["site", "method"], as_index=False).service_kw.mean().rename(columns={"service_kw": "mean_service_kw"})
    g["lower"] = g["mean_service_kw"]
    g["upper"] = g["mean_service_kw"]
    return g


def frontier(results: Path, out: Path) -> None:
    d = _frontier_data(results)
    sites = sorted(d.site.astype(str).unique())
    if not sites:
        raise ValueError(f"no policy rows found in {results}")
    # Keep the deliberately loose constant-bound counterfactual in its own row.
    # A single shared y-axis would visually compress the three deliverable
    # policies around 130--140 kW and make their uncertainty unreadable.
    fig, axes = plt.subplots(
        2, len(sites), figsize=(4.2 * len(sites), 5.3),
        gridspec_kw={"height_ratios": [1.45, 0.9]}, squeeze=False,
    )
    for j, site in enumerate(sites):
        ax = axes[0, j]
        cb_ax = axes[1, j]
        g = d[d.site.astype(str) == site].set_index("method")
        delivery = METHODS[:3]
        vals = [float(g.loc[m, "mean_service_kw"]) if m in g.index else np.nan for m in delivery]
        lows = [vals[i] - float(g.loc[m, "lower"]) if m in g.index else np.nan for i, m in enumerate(delivery)]
        highs = [float(g.loc[m, "upper"]) - vals[i] if m in g.index else np.nan for i, m in enumerate(delivery)]
        x = np.arange(len(delivery))
        for i, method in enumerate(delivery):
            if method not in g.index:
                continue
            ax.errorbar([x[i]], [vals[i]], yerr=[[lows[i]], [highs[i]]], fmt="o",
                        markersize=5.5, capsize=3.0, linewidth=1.1,
                        color=COLORS[method], ecolor="#222222",
                        markerfacecolor=COLORS[method], markeredgecolor="#222222",
                        markeredgewidth=0.45)
        ax.set_xticks(x, ["AC-bound\nLP", "Fixed\nrecovery", "Myopic\nrecovery"], fontsize=8)
        ax.set_title(f"IEEE-13 placement {site}")
        if np.isfinite(vals).any():
            finite_low = np.asarray([g.loc[m, "lower"] for m in delivery if m in g.index], float)
            finite_high = np.asarray([g.loc[m, "upper"] for m in delivery if m in g.index], float)
            pad = max(0.8, 0.08 * (finite_high.max() - finite_low.min()))
            ax.set_ylim(finite_low.min() - pad, finite_high.max() + pad)
        ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
        ax.set_axisbelow(True)
        cb = g.loc["energy_only"] if "energy_only" in g.index else None
        if cb is not None:
            cb_val = float(cb["mean_service_kw"])
            cb_low = cb_val - float(cb["lower"])
            cb_high = float(cb["upper"]) - cb_val
            cb_ax.errorbar([0], [cb_val], yerr=[[cb_low], [cb_high]], fmt="s",
                           markersize=5.5, capsize=3.0, color=COLORS["energy_only"],
                           ecolor="#333333", markeredgecolor="#222222", markeredgewidth=0.45)
            cb_ax.set_xticks([0], ["Constant-bound\ncounterfactual"], fontsize=8)
            cb_ax.set_ylim(cb_val - max(2.0, 1.8 * cb_low), cb_val + max(2.0, 1.8 * cb_high))
        else:
            cb_ax.set_xticks([])
        cb_ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
        cb_ax.set_axisbelow(True)
        if j == 0:
            ax.set_ylabel("Gated endpoint (kW)")
            cb_ax.set_ylabel("Counterfactual (kW)")
    fig.suptitle("Strict external-date network recovery frontier", y=0.995, fontsize=11)
    fig.text(0.5, -0.005, "Points and descriptive 95% date-cluster intervals; baseline-feasible AC profiles only (n=2,188 per site)",
             ha="center", va="top", fontsize=8, color="#555555")
    _save(fig, out, "fig1_external_frontier", rect=(0, 0.02, 1, 0.97))


def trace(trace_dir: Path, out: Path) -> None:
    path = trace_dir / "representative_trace.csv"
    if not path.exists():
        return
    d = pd.read_csv(path)
    fig, axes = plt.subplots(3, 1, figsize=(8.2, 7.0), sharex=True, gridspec_kw={"hspace": 0.12})
    for method in METHODS:
        g = d[d.method == method]
        if g.empty:
            continue
        axes[0].step(g.interval, g.discharge_kw, where="post", label=LABELS[method], color=COLORS[method], linewidth=1.8)
        axes[0].step(g.interval, -g.charge_kw, where="post", color=COLORS[method], linestyle="--", alpha=0.65, linewidth=1.0)
        axes[1].plot(g.interval, g.soc, marker=".", markersize=3.5, color=COLORS[method], linewidth=1.4)
        axes[2].plot(g.interval, g.charge_limit_kw, color=COLORS[method], alpha=0.85, linewidth=1.4)
    axes[0].set_ylabel("Battery power (kW)\n(+ export, − charge)")
    axes[1].set_ylabel("SOC")
    axes[1].axhline(0.2, color="#444444", linestyle=":", linewidth=0.8, label="SOC reserve")
    axes[2].set_ylabel("AC charge\nlimit (kW)")
    axes[2].set_xlabel("Half-hour interval")
    for ax in axes:
        for a, b in ((8, 12), (24, 28)):
            ax.axvspan(a - 0.5, b - 0.5, color="#F3C677", alpha=0.20, linewidth=0)
        for a, b in ((12, 24), (28, 48)):
            ax.axvspan(a - 0.5, b - 0.5, color="#8FD3E8", alpha=0.10, linewidth=0)
        ax.grid(color="#E2E2E2", linewidth=0.6)
        ax.set_axisbelow(True)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=2, fontsize=8, frameon=False,
               loc="upper center", bbox_to_anchor=(0.54, 0.965))
    fig.suptitle("Two-call contract: network headroom varies within the day", y=0.995, fontsize=11)
    _save(fig, out, "fig2_recovery_trace", rect=(0, 0, 1, 0.945))


def failure(results: Path, out: Path) -> None:
    d = _policy(results)
    d = d[d.baseline_feasible == 1]
    x = d.groupby(["site", "method"], as_index=False).replay_feasible.mean()
    sites = sorted(x.site.astype(str).unique())
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 3.8), gridspec_kw={"width_ratios": [1.7, 1.0]})
    ax = axes[0]
    zoom = axes[1]
    annotated_zoom = set()
    for method in METHODS:
        g = x[x.method == method]
        if g.empty:
            continue
        lookup = {str(row.site): float(row.replay_feasible) for row in g.itertuples()}
        rates = [1.0 - lookup.get(s, np.nan) for s in sites]
        ax.plot(sites, rates, marker="o", linewidth=1.8,
                markersize=5, label=LABELS[method], color=COLORS[method])
        for site, rate in zip(sites, rates):
            # Small-rate labels belong in the expanded panel, where they can
            # be separated from one another without hiding coincident lines.
            if method == "energy_only" and np.isfinite(rate):
                ax.annotate(f"{100*rate:.2f}%", (site, rate), xytext=(0, 7),
                            textcoords="offset points", ha="center", fontsize=7,
                            color=COLORS[method])
        if method != "energy_only":
            zoom.plot(sites, rates, marker="o", linewidth=1.8, markersize=5,
                      label=LABELS[method], color=COLORS[method])
            for site, rate in zip(sites, rates):
                key = (site, round(rate, 12))
                if np.isfinite(rate) and key not in annotated_zoom:
                    is_zero = abs(rate) < 1e-12
                    zoom.annotate(f"{100*rate:.2f}%", (site, rate),
                                  xytext=(0, -10 if is_zero else 7),
                                  textcoords="offset points", ha="center",
                                  va="top" if is_zero else "bottom", fontsize=7,
                                  color="#555555" if is_zero else COLORS[method])
                    annotated_zoom.add(key)
    ax.set_ylabel("AC replay failure rate")
    ax.set_xlabel("Battery placement")
    ax.set_ylim(-0.02, 1.05)
    ax.set_yticks(np.linspace(0, 1, 6), [f"{100*v:.0f}%" for v in np.linspace(0, 1, 6)])
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncol=2, loc="upper left", bbox_to_anchor=(0.0, 0.87))
    zoom.set_title("Other policies", fontsize=9)
    zoom.set_xlabel("Battery placement")
    zoom.set_ylim(-0.0002, 0.0010)
    zoom.margins(x=0.16)
    zoom.set_yticks([0.0, 0.0005, 0.0010], ["0%", "0.05%", "0.10%"])
    zoom.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    zoom.set_axisbelow(True)
    zoom.legend(frameon=False, fontsize=7, loc="upper left")
    fig.text(0.5, -0.01, "Conditional on the baseline AC-feasibility gate; the constant-bound counterfactual is shown at 100% in the left panel",
             ha="center", va="top", fontsize=8, color="#555555")
    _save(fig, out, "fig3_failure_rates")


def mechanism(results: Path, out: Path) -> None:
    path = results / "mechanism" / "headroom_effects.csv"
    if not path.exists():
        return
    d = pd.read_csv(path)
    fig, ax = plt.subplots(figsize=(6.8, 4.0))
    site_colors = {"611.3": "#0072B2", "634.1": "#D55E00", "675.1": "#009E73"}
    for site in sorted(d.site.astype(str).unique()):
        g = d[d.site.astype(str) == site]
        ax.scatter(g.charge_cv, g.lp_minus_myopic_kw, s=8, alpha=0.22,
                   color=site_colors.get(site, "#666666"), label=f"Placement {site}")
        if len(g) > 1:
            coef = np.polyfit(g.charge_cv, g.lp_minus_myopic_kw, 1)
            x = np.linspace(float(g.charge_cv.min()), float(g.charge_cv.max()), 50)
            ax.plot(x, coef[0] * x + coef[1], color=site_colors.get(site, "#666666"), linewidth=1.5)
    ax.axhline(0.0, color="#444444", linestyle=":", linewidth=0.8)
    ax.set_xlabel("Recovery-window AC charge-headroom range / mean")
    ax.set_ylabel("AC-bound LP − myopic service power (kW)")
    ax.set_title("Observed LP--myopic gap versus recovery headroom")
    ax.grid(color="#E2E2E2", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    _save(fig, out, "fig4_headroom_mechanism")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--trace-dir", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    frontier(args.results_dir, args.out_dir)
    trace(args.trace_dir, args.out_dir)
    failure(args.results_dir, args.out_dir)
    mechanism(args.results_dir, args.out_dir)
    print(f"wrote figures to {args.out_dir}")


if __name__ == "__main__":
    main()
