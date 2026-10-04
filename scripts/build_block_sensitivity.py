#!/usr/bin/env python3
"""Summarize leave-one-calendar-block sensitivity for the strict run."""
from __future__ import annotations

import argparse
from pathlib import Path
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv"
DEFAULT_OUT = ROOT / "results/network_recovery_external_2012_2013_strict_v4/statistics/block_leave_one_out.csv"


def _block_labels(dates: pd.Series) -> dict[pd.Timestamp, int]:
    unique = sorted(pd.to_datetime(dates).dt.normalize().unique())
    if not unique:
        return {}
    labels: dict[pd.Timestamp, int] = {}
    block = 0
    labels[unique[0]] = block
    for previous, current in zip(unique, unique[1:]):
        if (current - previous).days != 1:
            block += 1
        labels[current] = block
    return labels


def build(policy_path: Path = DEFAULT_POLICY, out_path: Path = DEFAULT_OUT) -> pd.DataFrame:
    rows = pd.read_csv(policy_path)
    required = {"date", "site", "method", "service_kw", "baseline_feasible"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"policy table missing columns: {missing}")
    rows["date"] = pd.to_datetime(rows["date"])
    rows["site"] = rows["site"].astype(str)
    rows["baseline_feasible"] = rows["baseline_feasible"].astype(int)
    labels = _block_labels(rows["date"])
    rows["block"] = rows["date"].dt.normalize().map(labels)
    eligible = rows[rows["baseline_feasible"].eq(1)].copy()
    # Match the primary estimator: average groups within date, then average
    # dates equally.  The output records both the full estimate and every
    # leave-one-block estimate so the sensitivity is auditable.
    date_means = (
        eligible.groupby(["site", "method", "block", "date"], as_index=False)["service_kw"]
        .mean()
    )
    records: list[dict[str, object]] = []
    for (site, method), group in date_means.groupby(["site", "method"], sort=True):
        full = float(group["service_kw"].mean())
        blocks = sorted(group["block"].unique())
        for excluded in [None, *blocks]:
            kept = group if excluded is None else group[group["block"] != excluded]
            records.append(
                {
                    "site": site,
                    "method": method,
                    "excluded_block": "none" if excluded is None else int(excluded),
                    "estimate_kw": float(kept["service_kw"].mean()),
                    "n_dates": int(kept["date"].nunique()),
                    "full_estimate_kw": full,
                }
            )
    out = pd.DataFrame(records)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    result = build(args.policy, args.out)
    print(result.to_string(index=False))
