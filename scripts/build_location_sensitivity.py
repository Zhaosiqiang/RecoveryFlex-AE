#!/usr/bin/env python3
"""Summarize the seven-site placement sensitivity after its run completes.

The placement run writes one row per ``date x group x site x method`` to
``policy_rows.csv``.  This script is intentionally a post-processing step:
it reads that table only, applies the recorded zero-command gate, and does
not rerun OpenDSS or change the strict-v4 primary result.  Date-cluster
percentile bootstrap intervals are the primary uncertainty summary.  Paired
network-LP minus baseline effects retain the date x group pairing used by the
dispatch experiment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from cluster_statistics import cluster_bootstrap


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "results" / "location_sensitivity_external_2012_2013_strict_v4"
DEFAULT_OUT = DEFAULT_RESULTS / "statistics"

# This is the predeclared order from placement_sweep_audit.md.  Keeping it
# explicit makes the x-axis stable across reruns and makes the PV-coincident
# location (675.1) visible rather than hiding it in alphabetical sorting.
SITES = ("611.3", "634.1", "675.1", "652.1", "645.3", "646.3", "684.3")
METHODS = ("network_lp", "fixed_recovery", "myopic_recovery")
BASELINES = ("fixed_recovery", "myopic_recovery")
# The location runner reuses the strict-v4 driver, which may also emit an
# energy-only counterfactual.  It is accepted for pairing/gate validation but
# intentionally excluded from the requested network/fixed/myopic summaries.
OPTIONAL_METHODS = ("energy_only",)
ALLOWED_METHODS = set(METHODS) | set(OPTIONAL_METHODS)
OUTCOMES = ("service_kw", "planner_feasible", "replay_feasible")
POPULATIONS = ("all", "baseline_feasible")


def _as_numeric(frame: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Convert required numeric columns and fail on missing/non-finite data."""
    out = frame.copy()
    for column in columns:
        out[column] = pd.to_numeric(out[column], errors="coerce")
        if out[column].isna().any() or not np.isfinite(out[column].to_numpy(float)).all():
            raise ValueError(f"{column} contains missing or non-finite values")
    return out


def validate(rows: pd.DataFrame, sites: tuple[str, ...] = SITES) -> pd.DataFrame:
    """Validate the paired policy table before calculating any summaries."""
    required = {"date", "group", "site", "method", "service_kw", "baseline_feasible"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"policy_rows.csv is missing required columns: {missing}")

    rows = rows.copy()
    rows["date"] = rows["date"].astype(str)
    rows["site"] = rows["site"].astype(str)
    rows["method"] = rows["method"].astype(str)
    rows = _as_numeric(rows, ["group", "service_kw", "baseline_feasible"])
    if not rows["group"].eq(np.floor(rows["group"])).all():
        raise ValueError("group must contain integer labels")
    if not rows["baseline_feasible"].isin([0, 1]).all():
        raise ValueError("baseline_feasible must be a 0/1 gate")
    rows["group"] = rows["group"].astype(int)
    rows["baseline_feasible"] = rows["baseline_feasible"].astype(int)

    observed_sites = set(rows["site"])
    missing_sites = [site for site in sites if site not in observed_sites]
    unexpected_sites = sorted(observed_sites - set(sites))
    if missing_sites or unexpected_sites:
        raise ValueError(
            "expected exactly the predeclared seven sites; "
            f"missing={missing_sites}, unexpected={unexpected_sites}"
        )
    observed_methods = set(rows["method"])
    unexpected_methods = sorted(observed_methods - ALLOWED_METHODS)
    missing_methods = sorted(set(METHODS) - observed_methods)
    if unexpected_methods or missing_methods:
        raise ValueError(
            "expected network/fixed/myopic methods (energy_only is optional); "
            f"missing={missing_methods}, unexpected={unexpected_methods}"
        )
    key = ["date", "group", "site", "method"]
    duplicate = rows.duplicated(key, keep=False)
    if duplicate.any():
        examples = rows.loc[duplicate, key].head(5).to_dict("records")
        raise ValueError(f"duplicate policy rows for paired units: {examples}")
    target_counts = (
        rows[rows["method"].isin(METHODS)]
        .groupby(["date", "group", "site"], sort=False)["method"]
        .nunique()
    )
    incomplete = target_counts[target_counts != len(METHODS)]
    if not incomplete.empty:
        raise ValueError(
            "each date x group x site must contain all three methods; "
            f"incomplete units={incomplete.head(5).to_dict()}"
        )

    # The baseline gate is a property of the profile/site operating point, so
    # it must be identical across all methods in each paired unit.
    gate_counts = rows.groupby(["date", "group", "site"], sort=False)["baseline_feasible"].nunique()
    inconsistent = gate_counts[gate_counts != 1]
    if not inconsistent.empty:
        raise ValueError(
            "baseline_feasible differs across methods for paired units; "
            f"examples={inconsistent.head(5).to_dict()}"
        )
    return rows


def _cluster_bootstrap(
    frame: pd.DataFrame,
    value: str,
    seed: int,
    n_boot: int,
    context: tuple[object, ...],
) -> dict[str, float | int]:
    """Return a deterministic date-cluster bootstrap summary."""
    return cluster_bootstrap(
        frame,
        value,
        ("date",),
        seed,
        n_boot,
        context=context + ("date",),
        count_name="n_dates",
    )


def _population(rows: pd.DataFrame, population: str) -> pd.DataFrame:
    if population == "all":
        return rows
    if population == "baseline_feasible":
        return rows[rows["baseline_feasible"] == 1]
    raise ValueError(population)


def _method_summary(
    rows: pd.DataFrame,
    seed: int,
    n_boot: int,
    sites: tuple[str, ...],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for population in POPULATIONS:
        population_rows = _population(rows, population)
        for site in sites:
            site_rows = population_rows[population_rows["site"] == site]
            for method in METHODS:
                method_rows = site_rows[site_rows["method"] == method]
                for outcome in OUTCOMES:
                    # Replay/planner columns were added by the full runner;
                    # service-only smoke tables remain analyzable if they do
                    # not contain those optional outcomes.
                    if outcome not in method_rows.columns:
                        continue
                    result = _cluster_bootstrap(
                        method_rows,
                        outcome,
                        seed,
                        n_boot,
                        ("method", population, site, method, outcome),
                    )
                    records.append(
                        {
                            "population": population,
                            "site": site,
                            "method": method,
                            "outcome": outcome,
                            "cluster_level": "date",
                            **result,
                        }
                    )
    return pd.DataFrame(records)


def _paired_effects(rows: pd.DataFrame) -> pd.DataFrame:
    """Create one paired row per date x group x site and baseline."""
    keys = ["date", "group", "site", "baseline_feasible"]
    values = ["service_kw"]
    for optional in ("planner_feasible", "replay_feasible"):
        if optional in rows.columns:
            values.append(optional)
    wide = rows.pivot(index=keys, columns="method", values=values)
    wide.columns = [f"{value}__{method}" for value, method in wide.columns]
    wide = wide.reset_index()
    for baseline in BASELINES:
        for value in values:
            wide[f"{value}_diff__network_lp_minus_{baseline}"] = (
                wide[f"{value}__network_lp"] - wide[f"{value}__{baseline}"]
            )
    return wide


def _effect_summary(
    effects: pd.DataFrame,
    seed: int,
    n_boot: int,
    sites: tuple[str, ...],
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    population_effects = effects[effects["baseline_feasible"] == 1]
    values = ["service_kw"]
    for optional in ("planner_feasible", "replay_feasible"):
        if any(column.startswith(f"{optional}_diff__") for column in effects.columns):
            values.append(optional)
    for site in sites:
        site_effects = population_effects[population_effects["site"] == site]
        for baseline in BASELINES:
            for value in values:
                column = f"{value}_diff__network_lp_minus_{baseline}"
                result = _cluster_bootstrap(
                    site_effects,
                    column,
                    seed,
                    n_boot,
                    ("effect", "baseline_feasible", site, baseline, value),
                )
                records.append(
                    {
                        "population": "baseline_feasible",
                        "site": site,
                        "comparison": f"network_lp - {baseline}",
                        "baseline": baseline,
                        "outcome": f"{value}_difference",
                        "cluster_level": "date",
                        **result,
                    }
                )
    return pd.DataFrame(records)


def _plot_frontier(
    summary: pd.DataFrame,
    out_dir: Path,
    sites: tuple[str, ...],
) -> None:
    """Write a topology/placement panel and frontier panel with date-cluster CIs."""
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    frontier = summary[
        (summary["population"] == "baseline_feasible")
        & (summary["outcome"] == "service_kw")
        & (summary["cluster_level"] == "date")
    ].copy()
    if frontier.empty:
        raise ValueError("no baseline-feasible service summaries available for plot")

    labels = {
        "network_lp": "AC-bound LP",
        "fixed_recovery": "Fixed recovery",
        "myopic_recovery": "Myopic recovery",
    }
    colors = {
        "network_lp": "#0072B2",
        "fixed_recovery": "#D55E00",
        "myopic_recovery": "#009E73",
    }
    x = np.arange(len(sites), dtype=float)
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "legend.fontsize": 9,
            "xtick.labelsize": 9,
            "ytick.labelsize": 10,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    # The coordinates are the public IEEE-13 bus coordinate fixture.  The
    # explicit edge list follows the feeder line definitions and keeps the
    # physical meaning of a bus.phase label visible to a reviewer.
    coords_path = ROOT / "data" / "raw" / "IEEE13Node_BusXY.csv"
    coords = {}
    if coords_path.exists():
        for line in coords_path.read_text().splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) == 3:
                coords[fields[0].casefold()] = (float(fields[1]), float(fields[2]))
    edges = [
        ("SourceBus", "650"), ("650", "RG60"), ("RG60", "632"),
        ("632", "670"), ("670", "671"), ("671", "680"),
        ("632", "633"), ("633", "634"), ("632", "645"),
        ("645", "646"), ("671", "684"), ("684", "611"),
        ("684", "652"), ("671", "692"), ("692", "675"),
    ]
    fallback = {
        "sourcebus": (200.0, 400.0), "650": (200.0, 350.0), "rg60": (200.0, 300.0),
        "632": (200.0, 250.0), "633": (350.0, 250.0), "634": (400.0, 250.0),
        "670": (200.0, 200.0), "671": (200.0, 100.0), "680": (200.0, 0.0),
        "645": (100.0, 150.0), "646": (0.0, 150.0), "684": (100.0, 50.0),
        "611": (0.0, 50.0), "652": (100.0, 0.0), "692": (250.0, 50.0),
        "675": (400.0, 50.0),
    }
    coords = {**fallback, **coords}
    fig, (top, ax) = plt.subplots(
        1,
        2,
        figsize=(12.2, 5.3),
        gridspec_kw={"width_ratios": [1.0, 1.45]},
        constrained_layout=True,
    )
    for start, end in edges:
        x0, y0 = coords[start.casefold()]
        x1, y1 = coords[end.casefold()]
        top.plot([x0, x1], [y0, y1], color="#8A8A8A", linewidth=1.6, zorder=1)
    node_names = sorted({node for edge in edges for node in edge}, key=lambda n: n.casefold())
    for node in node_names:
        x0, y0 = coords[node.casefold()]
        top.scatter([x0], [y0], s=28, color="#4C4C4C", zorder=2)
        top.text(x0 + 7, y0 + 5, node, fontsize=7.5, color="#303030")
    battery_sites = {site.split(".", 1)[0] for site in sites}
    for site in sites:
        bus = site.split(".", 1)[0]
        x0, y0 = coords[bus.casefold()]
        if site == "675.1":
            top.scatter([x0], [y0], s=150, marker="*", color="#CC3311", edgecolor="white", linewidth=0.8, zorder=5)
            top.text(x0 + 8, y0 - 13, "675.1 PV + battery", fontsize=7.5, color="#99220D")
        else:
            top.scatter([x0], [y0], s=74, marker="o", facecolor="#0072B2", edgecolor="white", linewidth=0.8, zorder=4)
            top.text(x0 + 8, y0 + 13, site, fontsize=7.5, color="#005A8D")
    top.set_title("A. IEEE-13 placement set", fontsize=12)
    top.set_aspect("equal", adjustable="datalim")
    top.axis("off")
    top.legend(
        handles=[
            Line2D([0], [0], marker="o", color="none", markerfacecolor="#0072B2", markeredgecolor="white", label="battery placement", markersize=7),
            Line2D([0], [0], marker="*", color="none", markerfacecolor="#CC3311", markeredgecolor="white", label="PV + battery at 675.1", markersize=10),
        ],
        loc="upper left",
        bbox_to_anchor=(0.0, 1.0),
        frameon=False,
        fontsize=8,
    )
    for method in METHODS:
        points = frontier[frontier["method"] == method].set_index("site").reindex(sites)
        if points["estimate"].isna().any():
            raise ValueError(f"missing baseline-feasible summaries for method={method}")
        y = points["estimate"].to_numpy(float)
        y_low = points["ci_low"].to_numpy(float)
        y_high = points["ci_high"].to_numpy(float)
        ax.plot(
            x,
            y,
            marker="o",
            markersize=5.5,
            linewidth=2.0,
            color=colors[method],
            label=labels[method],
            zorder=3,
        )
        ax.fill_between(x, y_low, y_high, color=colors[method], alpha=0.12, linewidth=0, zorder=1)

    ax.set_xticks(x, sites)
    ax.set_xlabel("Battery placement (IEEE-13 bus.phase)")
    ax.set_ylabel("Service frontier (kW; baseline-feasible profiles)")
    ax.set_title("B. Repeated-service frontier by placement")
    ax.grid(axis="y", color="#B0B0B0", alpha=0.30, linewidth=0.8)
    ax.grid(axis="x", visible=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(loc="best", frameon=False)
    ax.margins(x=0.04)

    out_dir.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_dir / "location_frontier.png", dpi=320, bbox_inches="tight")
    fig.savefig(out_dir / "location_frontier.pdf", bbox_inches="tight")
    plt.close(fig)


def run(
    results_dir: Path = DEFAULT_RESULTS,
    out_dir: Path = DEFAULT_OUT,
    n_boot: int = 5000,
    seed: int = 20261003,
    sites: tuple[str, ...] = SITES,
) -> dict[str, object]:
    """Build clustered summaries and figure from a completed placement run."""
    source = results_dir / "policy_rows.csv"
    if not source.exists():
        raise FileNotFoundError(
            f"{source} does not exist; run the seven-site experiment first"
        )
    rows = validate(pd.read_csv(source), sites)
    optional_numeric = [column for column in ("planner_feasible", "replay_feasible") if column in rows.columns]
    if optional_numeric:
        rows = _as_numeric(rows, optional_numeric)

    out_dir.mkdir(parents=True, exist_ok=True)
    method_summary = _method_summary(rows, seed, n_boot, sites)
    effects = _paired_effects(rows)
    effect_summary = _effect_summary(effects, seed, n_boot, sites)
    method_summary.to_csv(out_dir / "method_summary.csv", index=False)
    effect_summary.to_csv(out_dir / "paired_effects.csv", index=False)
    # Keep the conventional name used by the main strict-v4 statistics
    # builder while retaining the more descriptive paired_effects.csv name.
    effect_summary.to_csv(out_dir / "statistics.csv", index=False)
    effects.to_csv(out_dir / "paired_units.csv", index=False)
    _plot_frontier(method_summary, out_dir, sites)

    gate = (
        rows.groupby(["date", "group", "site"], sort=False, as_index=False)["baseline_feasible"]
        .first()
    )
    units = gate[["date", "group", "site"]].copy()
    gate_summary = (
        gate.groupby("site", sort=False)["baseline_feasible"]
        .agg(n_units="size", n_baseline_feasible="sum", baseline_feasible_rate="mean")
        .reindex(sites)
        .reset_index()
    )
    gate_summary.to_csv(out_dir / "baseline_gate_by_site.csv", index=False)

    metadata = {
        "status": "location_sensitivity_clustered_statistics_v2_deterministic",
        "source_results": str(results_dir.resolve()),
        "source_policy_rows": str(source.resolve()),
        "n_rows": int(len(rows)),
        "n_sites": int(rows["site"].nunique()),
        "sites": list(sites),
        "methods": list(METHODS),
        "n_dates": int(rows["date"].nunique()),
        "n_date_group_site_units": int(len(units)),
        "primary_population": "baseline_feasible",
        "primary_cluster_level": "date",
        "paired_unit": "date x group x site",
        "bootstrap_replicates": int(n_boot),
        "seed": int(seed),
        "rng_protocol": "SHA256(seed, context) -> PCG64; sorted date keys; one stream per summary row",
        "percentile_interval": [0.025, 0.975],
        "interpretation": "Positive network_lp minus baseline service effect means the hindsight network policy supports a higher constant service power for the same date x group x site profile.",
    }
    (out_dir / "statistics.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=20261003)
    args = parser.parse_args()
    print(json.dumps(run(args.results_dir, args.out_dir, args.bootstrap, args.seed), indent=2))


if __name__ == "__main__":
    main()
