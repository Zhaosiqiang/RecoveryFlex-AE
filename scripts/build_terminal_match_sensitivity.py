#!/usr/bin/env python3
"""Replay a balanced endpoint sample under alternative command-match tolerances."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from audit_claims_round1 import embed, feeder, main_dispatch, sample_units

ROOT = Path(__file__).resolve().parents[1]


def run(primary: Path, source: Path, out_dir: Path) -> pd.DataFrame:
    load, pv, dates, _ = embed(source)
    gate = pd.read_csv(primary / "baseline_zero_audit.csv")
    gate["site"] = gate.site.astype(str)
    units = sample_units(gate, n_dates=2)
    bounds = pd.read_csv(primary / "ac_bounds.csv")
    bounds["site"] = bounds.site.astype(str)
    tolerances = (0.005, 0.01, 0.02)
    feeders = {site: {rtol: feeder(site, relative_command_tol=rtol) for rtol in tolerances} for site in sorted(units.site.unique())}
    rows = []
    for u in units.itertuples(index=False):
        site, day, group = str(u.site), int(u.day_index), int(u.group)
        ld, pv_d = load[day, :48, group], pv[day, :48, group]
        b = bounds[(bounds.site == site) & (bounds.day_index == day) & (bounds.group == group)].sort_values("interval")
        lp = main_dispatch(b.charge_limit_kw.to_numpy(float), b.export_limit_kw.to_numpy(float), ld)
        for rtol in tolerances:
            f = feeders[site][rtol]
            audits = [f.solve(float(l), float(v), {site: float(d - c)}) for l, v, c, d in zip(ld, pv_d, lp.charge_kw, lp.discharge_kw)]
            ok = bool(lp.feasible and all(a.feasible for a in audits))
            rows.append({"date": str(dates[day]), "day_index": day, "group": group, "site": site,
                         "relative_command_tolerance": rtol, "service_endpoint_kw": float(lp.service_kw),
                         "replay_feasible": int(ok)})
    frame = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / "terminal_match_sensitivity_sample.csv", index=False)
    summary = frame.groupby("relative_command_tolerance", as_index=False).agg(
        n=("replay_feasible", "size"), replay_success=("replay_feasible", "mean"),
        mean_endpoint_kw=("service_endpoint_kw", "mean"), min_endpoint_kw=("service_endpoint_kw", "min"),
        max_endpoint_kw=("service_endpoint_kw", "max"),
    )
    summary.to_csv(out_dir / "terminal_match_sensitivity_summary.csv", index=False)
    (out_dir / "terminal_match_sensitivity_metadata.json").write_text(json.dumps({
        "status": "terminal_match_tolerance_sensitivity_v1",
        "sample": "audit_claims_round1.sample_units(n_dates=2): 40 units across two sites",
        "relative_command_tolerances": list(tolerances),
        "result": "All endpoint schedules were replayed under each setting; endpoint values are unchanged because the scalar endpoint is fixed by the recorded AC bounds.",
    }, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, default=ROOT / "results/network_recovery_external_2012_2013_strict_v4")
    parser.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/ac_coverage_audit_round1")
    args = parser.parse_args()
    print(run(args.primary, args.source, args.out_dir).to_string(index=False))
