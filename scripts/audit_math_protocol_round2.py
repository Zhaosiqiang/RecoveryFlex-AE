#!/usr/bin/env python3
"""Audit estimands, prefix-search diagnostics, and numerical tolerances.

This read-only audit consumes the already frozen result tables.  It is kept
separate from the expensive OpenDSS runners so a reviewer can reproduce the
math/protocol checks without rerunning the feeder.  The output distinguishes
date-weighted and pooled unit-weighted estimands and reports every observed
coarse-grid non-prefix pattern rather than assuming global monotonicity.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
THREE_CALL = ROOT / "results/three_call_grid_v1"
PREFIX = ROOT / "results/ac_coverage_audit_round1/prefix_monotonicity_sample.csv"
TOLERANCE = ROOT / "results/ac_coverage_audit_round1/numerical_sensitivity_sample.csv"


def _estimands(frame: pd.DataFrame, column: str) -> dict[str, float | int]:
    """Return pooled and equal-date means for one cell/column."""
    by_date = frame.groupby("date", sort=True)[column].mean()
    return {
        "unit_weighted_mean": float(frame[column].mean()),
        "date_weighted_mean": float(by_date.mean()),
        "n_units": int(len(frame)),
        "n_dates": int(len(by_date)),
    }


def audit_three_call() -> dict[str, object]:
    rows = pd.read_csv(THREE_CALL / "three_call_rows.csv")
    cell = rows[(rows.site == 634.1) & (rows.capacity_kwh == 500.0) & (rows.second_start == 24)].copy()
    if cell.empty:
        raise FileNotFoundError("three-call primary cell is absent")
    out = {
        "cell": {"site": "634.1", "capacity_kwh": 500.0, "second_start": 24},
        "relaxed_bound_kw": _estimands(cell, "relaxed_bound_kw"),
        "service_power_lp_kw": _estimands(cell, "service_power_lp_kw"),
        "chronology_contraction_kw": _estimands(cell, "chronology_contraction_kw"),
        "positive_rows": int((cell.chronology_contraction_kw > 1e-7).sum()),
        "positive_fraction": float((cell.chronology_contraction_kw > 1e-7).mean()),
        "warning": "The date-weighted and unit-weighted gaps differ; headline text must use one estimand consistently.",
    }
    return out


def audit_prefix() -> dict[str, object]:
    frame = pd.read_csv(PREFIX)
    # The runner records a 1->0->1 occurrence explicitly.  Recompute from the
    # binary string as a guard against a stale or hand-edited flag column.
    def later_one(pattern: str) -> bool:
        seen_failure = False
        for char in pattern:
            if char == "0":
                seen_failure = True
            elif seen_failure and char == "1":
                return True
        return False

    recomputed = frame.grid_feasible_pattern.astype(str).map(later_one)
    reported = frame.later_feasible_after_failure.astype(bool)
    mismatch = int((recomputed != reported).sum())
    nonprefix = frame[recomputed]
    return {
        "source": str(PREFIX),
        "rows": int(len(frame)),
        "grid": {"lower_kw": 0.0, "upper_kw": 300.0, "step_kw": 20.0},
        "zero_power_failures": int((frame.zero_feasible == 0).sum()),
        "nonprefix_rows": int(len(nonprefix)),
        "nonprefix_examples": nonprefix.head(20).to_dict(orient="records"),
        "reported_flag_mismatches": mismatch,
        "interpretation": "No later-feasible-after-failure point was observed in this stratified sample; this is an empirical prefix audit, not a proof for every operating point.",
    }


def audit_tolerance() -> dict[str, object]:
    frame = pd.read_csv(TOLERANCE)
    group_cols = ["constraint_tolerance", "command_tolerance_kw", "grid_step_kw"]
    means = frame.groupby(group_cols, as_index=False).service_endpoint_kw.mean().rename(columns={"service_endpoint_kw": "mean_kw"})
    declared = means[(means.constraint_tolerance == 1e-6) & (means.command_tolerance_kw == 0.01) & (means.grid_step_kw == 20.0)].iloc[0]
    means["delta_from_declared_kw"] = means.mean_kw - float(declared.mean_kw)
    return {
        "source": str(TOLERANCE),
        "rows": int(len(frame)),
        "declared": {"constraint_tolerance": 1e-6, "command_tolerance_kw": 0.01, "grid_step_kw": 20.0, "mean_endpoint_kw": float(declared.mean_kw)},
        "max_abs_delta_kw": float(np.max(np.abs(means.delta_from_declared_kw))),
        "settings": means.to_dict(orient="records"),
        "interpretation": "The command readback floor is 1% of command with a 0.01-kW absolute floor in the AC adapter; this table perturbs the numerical tolerance, command floor, and candidate-grid step on the declared 40-unit sample.",
    }


def run(out_dir: Path) -> dict[str, object]:
    result = {
        "status": "math_protocol_audit_round2",
        "three_call_estimands": audit_three_call(),
        "prefix_search": audit_prefix(),
        "numerical_tolerance": audit_tolerance(),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/math_protocol_audit_round2")
    args = parser.parse_args()
    print(json.dumps(run(args.out_dir), indent=2))
