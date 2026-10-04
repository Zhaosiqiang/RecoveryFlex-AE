#!/usr/bin/env python3
"""Block-stratified uncertainty summaries for the retained Ausgrid evaluation.

The primary paper intervals are date-cluster descriptive intervals.  This
supplement adds a prespecified calendar-block sensitivity: date means are
calculated separately for each retained contiguous block, then dates are
resampled within each block and combined with the observed block-date weights.
This does not claim independence between blocks or a future guarantee.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from cluster_statistics import _stable_rng

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = ROOT / "results" / "network_recovery_external_2012_2013_strict_v4"
DEFAULT_OUT = DEFAULT_RESULTS / "statistics"
METHODS = ("network_lp", "fixed_recovery", "myopic_recovery", "energy_only")
OUTCOMES = ("service_kw", "replay_feasible")

BLOCKS = (
    ("2012-07--2012-10", "2012-07-01", "2012-10-11"),
    ("2013-01", "2013-01-01", "2013-01-25"),
    ("2013-04--2013-06", "2013-04-01", "2013-06-30"),
)


def assign_block(dates: pd.Series) -> pd.Series:
    values = pd.to_datetime(dates, errors="raise")
    out = pd.Series(pd.NA, index=dates.index, dtype="string")
    for label, start, end in BLOCKS:
        mask = (values >= pd.Timestamp(start)) & (values <= pd.Timestamp(end))
        out.loc[mask] = label
    if out.isna().any():
        raise ValueError(f"dates outside retained blocks: {dates[out.isna()].tolist()[:5]}")
    return out


def _validate(rows: pd.DataFrame) -> pd.DataFrame:
    required = {"date", "group", "site", "method", "service_kw", "replay_feasible", "baseline_feasible"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"missing columns: {missing}")
    rows = rows.copy()
    rows["date"] = rows["date"].astype(str)
    rows["group"] = pd.to_numeric(rows["group"], errors="raise").astype(int)
    rows["site"] = rows["site"].astype(str)
    rows["method"] = rows["method"].astype(str)
    for col in ("service_kw", "replay_feasible", "baseline_feasible"):
        rows[col] = pd.to_numeric(rows[col], errors="raise")
    if sorted(rows.method.unique()) != sorted(METHODS):
        raise ValueError(f"unexpected methods: {sorted(rows.method.unique())}")
    rows["block"] = assign_block(rows["date"])
    rows["date"] = pd.to_datetime(rows["date"]).dt.strftime("%Y-%m-%d")
    return rows


def _date_means(frame: pd.DataFrame, value: str) -> pd.DataFrame:
    return frame.groupby(["block", "date"], sort=True, as_index=False)[value].mean()


def _stratified_bootstrap(frame: pd.DataFrame, value: str, seed: int, reps: int, context: Iterable[object]) -> dict[str, float | int | str]:
    date_means = _date_means(frame, value)
    if date_means.empty:
        return {"estimate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "n_pairs": 0, "n_dates": 0, "n_blocks": 0}
    by_block = {block: g[value].to_numpy(dtype=float) for block, g in date_means.groupby("block", sort=True)}
    weights = {block: len(vals) for block, vals in by_block.items()}
    total = float(sum(weights.values()))
    point = sum(weights[b] * vals.mean() for b, vals in by_block.items()) / total
    if reps <= 1:
        draws = np.array([point])
    else:
        rng = _stable_rng(seed, tuple(context) + ("stratified_block_dates",))
        draw_sum = np.zeros(reps, dtype=float)
        for block, vals in by_block.items():
            idx = rng.integers(0, len(vals), size=(reps, len(vals)))
            draw_sum += (len(vals) / total) * vals[idx].mean(axis=1)
        draws = draw_sum
    return {
        "estimate": float(point),
        "ci_low": float(np.quantile(draws, 0.025)),
        "ci_high": float(np.quantile(draws, 0.975)),
        "n_pairs": int(len(frame)),
        "n_dates": int(len(date_means)),
        "n_blocks": int(len(by_block)),
    }


def run(results_dir: Path, out_dir: Path, reps: int = 5000, seed: int = 20261003) -> dict:
    rows = _validate(pd.read_csv(results_dir / "policy_rows.csv"))
    rows = rows[rows.baseline_feasible.astype(int).eq(1)].copy()
    block_rows: list[dict] = []
    strat_rows: list[dict] = []
    for site in sorted(rows.site.unique()):
        for method in METHODS:
            work = rows[(rows.site == site) & (rows.method == method)]
            for outcome in OUTCOMES:
                for block, start, end in BLOCKS:
                    bw = work[work.block == block]
                    dm = _date_means(bw, outcome)
                    block_boot = _stratified_bootstrap(
                        bw, outcome, seed, reps,
                        ("block", site, method, outcome, block),
                    )
                    block_rows.append({
                        "site": site, "method": method, "outcome": outcome,
                        "block": block, "start": start, "end": end,
                        "estimate": float(dm[outcome].mean()),
                        "ci_low": float(block_boot["ci_low"]),
                        "ci_high": float(block_boot["ci_high"]),
                        "n_pairs": int(len(bw)), "n_dates": int(dm.date.nunique()),
                    })
                result = _stratified_bootstrap(work, outcome, seed, reps, ("stratified", site, method, outcome))
                strat_rows.append({"site": site, "method": method, "outcome": outcome, "cluster_level": "calendar_block_stratified_date", **result})
    out_dir.mkdir(parents=True, exist_ok=True)
    block_df = pd.DataFrame(block_rows)
    strat_df = pd.DataFrame(strat_rows)
    block_df.to_csv(out_dir / "block_summary.csv", index=False)
    strat_df.to_csv(out_dir / "block_stratified_summary.csv", index=False)
    metadata = {
        "status": "calendar_block_stratified_date_bootstrap_v1",
        "source_results": str(results_dir.resolve()),
        "population": "baseline_feasible",
        "blocks": [{"label": label, "start": start, "end": end} for label, start, end in BLOCKS],
        "bootstrap": {"replicates": int(reps), "seed": int(seed), "resampling": "dates within each block with observed block-date weights"},
        "interpretation": "descriptive retained-sample sensitivity; does not remove dependence between blocks and is not a future delivery guarantee",
        "files": ["block_summary.csv", "block_stratified_summary.csv", "block_stratified_metadata.json"],
    }
    (out_dir / "block_stratified_metadata.json").write_text(json.dumps(metadata, indent=2))
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
