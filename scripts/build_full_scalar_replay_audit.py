#!/usr/bin/env python3
"""Audit scalar-LP endpoints against the recorded nonlinear replay outcomes.

This is a provenance check over the authoritative policy table.  The scalar
endpoint is an interval-wise upper-bound screen; when its recorded schedule
passes every nonlinear readback, the table supports a zero observed
scalar-minus-replay gap for that gated unit.  It does not prove that the
independent interval bounds describe the joint AC-feasible set.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def run(policy_path: Path, out_dir: Path) -> pd.DataFrame:
    rows = pd.read_csv(policy_path)
    required = {"date", "day_index", "group", "site", "method", "service_kw",
                "planner_feasible", "replay_feasible", "baseline_feasible"}
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"policy table is missing columns: {missing}")
    gated = rows[(rows.method == "network_lp") & (rows.baseline_feasible == 1)].copy()
    if len(gated) != 4376:
        raise ValueError(f"expected 4,376 baseline-gated network rows, found {len(gated)}")
    if gated["replay_feasible"].astype(int).sum() != len(gated):
        raise ValueError("a baseline-gated network endpoint did not pass recorded replay")
    gated["scalar_minus_replay_endpoint_kw"] = 0.0
    gated["replay_endpoint_status"] = "exact_at_scalar_endpoint"
    gated["interpretation"] = (
        "recorded scalar endpoint schedule passed all nonlinear interval readbacks; "
        "zero observed gap is not a joint AC-set proof"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    columns = ["date", "day_index", "group", "site", "service_kw",
               "planner_feasible", "replay_feasible", "baseline_feasible",
               "scalar_minus_replay_endpoint_kw", "replay_endpoint_status",
               "interpretation"]
    gated[columns].to_csv(out_dir / "full_scalar_vs_replay.csv", index=False)
    summary = {
        "status": "full_scalar_endpoint_replay_audit_v1",
        "source": str(policy_path.relative_to(ROOT)),
        "method": "network_lp",
        "baseline_gate": "baseline_feasible == 1",
        "n_rows": int(len(gated)),
        "n_dates": int(gated.date.nunique()),
        "sites": sorted(gated.site.astype(str).unique()),
        "n_replay_pass": int(gated.replay_feasible.sum()),
        "max_abs_observed_gap_kw": 0.0,
        "interpretation": (
            "The authoritative policy table records a successful nonlinear replay "
            "for every baseline-gated scalar endpoint. This supports no observed "
            "negative scalar-minus-replay gap over 4,376 rows; it does not establish "
            "a joint nonlinear AC feasible-set equivalence or transferability."
        ),
        "script": "scripts/build_full_scalar_replay_audit.py",
    }
    (out_dir / "full_scalar_vs_replay_summary.json").write_text(json.dumps(summary, indent=2))
    return gated


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path,
                        default=ROOT / "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv")
    parser.add_argument("--out-dir", type=Path,
                        default=ROOT / "results/ac_coverage_audit_round1")
    args = parser.parse_args()
    frame = run(args.policy, args.out_dir)
    print(f"wrote {len(frame)} full scalar endpoint replay rows")
