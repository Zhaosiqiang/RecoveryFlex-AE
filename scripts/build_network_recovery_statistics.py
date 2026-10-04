#!/usr/bin/env python3
"""Clustered uncertainty analysis for the network-recovery experiment.

Rows in ``policy_rows.csv`` are paired at (date, group, site): every policy
sees the same measured profile and AC bound table.  The default publication
estimate uses a date-cluster bootstrap, which gives each date equal weight
and preserves correlation between customer groups on a day.  A paired
date-by-group bootstrap is also written for sensitivity analysis.

The script deliberately does not pool methods as independent samples.  It
returns absolute method summaries and paired network-LP minus baseline
effects, with reproducible percentile intervals and the bootstrap probability
that the effect is positive.
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
DEFAULT_RESULTS = ROOT / "results" / "network_recovery_external_2012_2013_strict_v4"
DEFAULT_OUT = ROOT / "results" / "network_recovery_external_2012_2013_strict_v4" / "statistics"
METHODS = ("network_lp", "fixed_recovery", "myopic_recovery", "energy_only")
BASELINES = tuple(m for m in METHODS if m != "network_lp")
OUTCOMES = ("service_kw", "replay_feasible")
POPULATIONS = ("all", "baseline_feasible")
CLUSTER_LEVELS = ("date", "date_group")


def _as_bool(series: pd.Series) -> pd.Series:
    """Normalize integer/boolean replay columns without changing NaNs."""
    return pd.to_numeric(series, errors="coerce").astype(float)


def _validate(rows: pd.DataFrame) -> pd.DataFrame:
    required = {
        "date", "group", "site", "method", "service_kw", "replay_feasible",
        "baseline_feasible",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"policy_rows.csv is missing required columns: {missing}")
    rows = rows.copy()
    rows["date"] = rows["date"].astype(str)
    rows["group"] = pd.to_numeric(rows["group"], errors="raise").astype(int)
    rows["site"] = rows["site"].astype(str)
    rows["method"] = rows["method"].astype(str)
    bad_method = sorted(set(rows.method) - set(METHODS))
    if bad_method:
        raise ValueError(f"unexpected method labels: {bad_method}")
    for c in ("service_kw", "replay_feasible", "baseline_feasible"):
        rows[c] = pd.to_numeric(rows[c], errors="coerce")
    if rows[["service_kw", "replay_feasible", "baseline_feasible"]].isna().any().any():
        raise ValueError("service_kw/replay_feasible/baseline_feasible contain NaN")
    key = ["date", "group", "site", "method"]
    duplicate = rows.duplicated(key, keep=False)
    if duplicate.any():
        examples = rows.loc[duplicate, key].head(5).to_dict("records")
        raise ValueError(f"duplicate policy rows for a paired unit: {examples}")
    counts = rows.groupby(["site", "date", "group"], sort=False).method.nunique()
    incomplete = counts[counts != len(METHODS)]
    if not incomplete.empty:
        raise ValueError(
            "each date×group×site must contain all four methods; "
            f"incomplete units={incomplete.head(5).to_dict()}"
        )
    return rows


def _cluster_bootstrap(
    frame: pd.DataFrame,
    value: str,
    level: str,
    seed: int,
    n_boot: int,
    context: tuple[object, ...],
) -> dict[str, float | int | str]:
    """Return a deterministic date/date-group cluster bootstrap summary."""
    if level == "date":
        columns = ("date",)
    elif level == "date_group":
        columns = ("date", "group")
    else:
        raise ValueError(f"unknown cluster level {level!r}")
    return cluster_bootstrap(
        frame,
        value,
        columns,
        seed,
        n_boot,
        context=context + (level,),
        count_name="n_clusters",
    )


def _population(rows: pd.DataFrame, population: str) -> pd.DataFrame:
    if population == "all":
        return rows
    if population == "baseline_feasible":
        return rows[rows.baseline_feasible == 1]
    raise ValueError(population)


def _paired_effects(rows: pd.DataFrame) -> pd.DataFrame:
    keys = ["date", "group", "site", "baseline_feasible"]
    values = ["service_kw", "replay_feasible"]
    wide = rows.pivot(index=keys, columns="method", values=values)
    wide.columns = [f"{v}__{m}" for v, m in wide.columns]
    wide = wide.reset_index()
    for baseline in BASELINES:
        for value in values:
            wide[f"{value}_diff__network_lp_minus_{baseline}"] = (
                wide[f"{value}__network_lp"] - wide[f"{value}__{baseline}"]
            )
    return wide


def _method_summaries(rows: pd.DataFrame, seed: int, n_boot: int) -> pd.DataFrame:
    records: list[dict] = []
    for population in POPULATIONS:
        pop = _population(rows, population)
        for site in sorted(pop.site.unique()):
            site_rows = pop[pop.site == site]
            for method in METHODS:
                mrows = site_rows[site_rows.method == method]
                for level in CLUSTER_LEVELS:
                    for outcome in OUTCOMES:
                        result = _cluster_bootstrap(
                            mrows,
                            outcome,
                            level,
                            seed,
                            n_boot,
                            ("method", population, site, method, outcome),
                        )
                        records.append({
                            "site": site, "population": population, "method": method,
                            "outcome": outcome, "cluster_level": level, **result,
                        })
    return pd.DataFrame(records)


def _paired_summaries(rows: pd.DataFrame, seed: int, n_boot: int) -> pd.DataFrame:
    records: list[dict] = []
    for population in POPULATIONS:
        pop = _population(rows, population)
        effects = _paired_effects(pop)
        for site in sorted(effects.site.unique()):
            site_effects = effects[effects.site == site]
            for baseline in BASELINES:
                for outcome in OUTCOMES:
                    col = f"{outcome}_diff__network_lp_minus_{baseline}"
                    for level in CLUSTER_LEVELS:
                        result = _cluster_bootstrap(
                            site_effects.rename(columns={col: "_effect"}),
                            "_effect",
                            level,
                            seed,
                            n_boot,
                            ("effect", population, site, baseline, outcome),
                        )
                        records.append({
                            "site": site, "population": population,
                            "comparison": f"network_lp - {baseline}",
                            "baseline": baseline, "outcome": f"{outcome}_difference",
                            "cluster_level": level, **result,
                        })
    return pd.DataFrame(records)


def run(results_dir: Path, out_dir: Path, n_boot: int = 5000, seed: int = 20261003) -> dict:
    rows = _validate(pd.read_csv(results_dir / "policy_rows.csv"))
    out_dir.mkdir(parents=True, exist_ok=True)
    # Each result row derives its own deterministic stream from ``seed`` and
    # its declared context.  Adding a site or changing loop order therefore
    # cannot change any existing interval.
    method_stats = _method_summaries(rows, seed, n_boot)
    paired_stats = _paired_summaries(rows, seed, n_boot)
    effects = _paired_effects(rows)
    method_stats.to_csv(out_dir / "method_summary.csv", index=False)
    paired_stats.to_csv(out_dir / "statistics.csv", index=False)
    effects.to_csv(out_dir / "paired_effects.csv", index=False)
    metadata = {
        "status": "network_recovery_clustered_statistics_v2_deterministic",
        "source_results": str(results_dir.resolve()),
        "n_rows": int(len(rows)),
        "n_sites": int(rows.site.nunique()),
        "n_dates": int(rows.date.nunique()),
        "n_date_group_units": int(rows[["date", "group", "site"]].drop_duplicates().shape[0]),
        "methods": list(METHODS),
        "primary_cluster_level": "date",
        "sensitivity_cluster_level": "date_group",
        "bootstrap_replicates": int(n_boot),
        "seed": int(seed),
        "rng_protocol": "SHA256(seed, context) -> PCG64; sorted cluster keys; one stream per summary row",
        "percentile_interval": [0.025, 0.975],
        "paired_unit": "date × group × site",
        "interpretation": "A positive paired difference means network_lp delivers more service or has a higher replay success rate.",
    }
    (out_dir / "statistics.json").write_text(json.dumps({
        "metadata": metadata,
        "method_summary": method_stats.to_dict(orient="records"),
        "paired_effects": paired_stats.to_dict(orient="records"),
    }, indent=2))
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--bootstrap", type=int, default=5000, help="number of cluster bootstrap replicates")
    parser.add_argument("--seed", type=int, default=20261003)
    args = parser.parse_args()
    print(json.dumps(run(args.results_dir, args.out_dir, args.bootstrap, args.seed), indent=2))


if __name__ == "__main__":
    main()
