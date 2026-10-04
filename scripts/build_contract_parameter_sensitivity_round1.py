#!/usr/bin/env python3
"""Run a small scalar-bound sensitivity audit for the chronology result.

The primary three-call grid is intentionally frozen.  This supplementary
audit varies initial SOC, terminal SOC, capacity, call separation, and
service-window length on a balanced 40-unit sample.  It uses the already
audited interval AC bounds and therefore measures contract sensitivity in the
scalar dispatch layer; it is not a new nonlinear replay or a population
estimate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from recoveryflex.dispatch import plan_service  # noqa: E402

DEFAULT_BOUNDS = ROOT / "results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv"
DEFAULT_POLICY = ROOT / "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv"
DEFAULT_OUT = ROOT / "results/contract_parameter_sensitivity_round1"


def _read(bounds_path: Path, policy_path: Path) -> tuple[pd.DataFrame, dict[tuple[str, int, int, str], tuple[np.ndarray, np.ndarray]]]:
    b = pd.read_csv(bounds_path)
    b["date"] = b.date.astype(str)
    b["site"] = b.site.astype(str)
    bound_map: dict[tuple[str, int, int, str], tuple[np.ndarray, np.ndarray]] = {}
    for key, g in b.groupby(["date", "day_index", "group", "site"], sort=False):
        g = g.sort_values("interval")
        if len(g) != 48:
            raise ValueError(f"expected 48 intervals for {key}")
        bound_map[(str(key[0]), int(key[1]), int(key[2]), str(key[3]))] = (
            g.charge_limit_kw.to_numpy(float), g.export_limit_kw.to_numpy(float)
        )
    p = pd.read_csv(policy_path)
    p["date"] = p.date.astype(str)
    p["site"] = p.site.astype(str)
    p = p[(p.method == "network_lp") & (p.baseline_feasible.astype(int) == 1) & p.site.isin(["611.3", "634.1"])].copy()
    p = p.drop_duplicates(["date", "day_index", "group", "site"])
    return p, bound_map


def _sample(policy: pd.DataFrame) -> pd.DataFrame:
    """Select two groups on ten spread dates at each primary placement."""
    rows = []
    for site, g in policy.groupby("site", sort=True):
        dates = np.linspace(0, int(g.day_index.max()), 10).round().astype(int)
        for day in dates:
            take = g[g.day_index == int(day)].sort_values("group").head(2)
            rows.append(take)
    out = pd.concat(rows, ignore_index=True).drop_duplicates(["date", "day_index", "group", "site"])
    if len(out) < 40:
        raise ValueError(f"balanced sample unexpectedly has {len(out)} rows")
    return out


def run(bounds_path: Path, policy_path: Path, out_dir: Path) -> dict[str, object]:
    policy, bound_map = _read(bounds_path, policy_path)
    sample = _sample(policy)
    rows: list[dict[str, object]] = []
    for r in sample.itertuples(index=False):
        charge, export = bound_map[(str(r.date), int(r.day_index), int(r.group), str(r.site))]
        for initial_soc in (0.60, 0.80):
            for terminal_soc in (0.60, 0.80):
                for capacity_kwh in (500.0, 1000.0, 2000.0):
                    for second_start in (20, 24):
                        for duration in (4, 6):
                            services = ((8, 8 + duration), (second_start, second_start + duration))
                            recovery = ((8 + duration, second_start), (second_start + duration, 48))
                            result = plan_service(
                                charge_limit_kw=charge,
                                export_limit_kw=export,
                                load_kw=np.zeros(48),
                                service_windows=services,
                                recovery_windows=recovery,
                                energy_kwh=capacity_kwh,
                                initial_soc=initial_soc,
                                terminal_soc_target=terminal_soc,
                                soc_min=0.20,
                                soc_max=1.00,
                                eta_charge=0.95,
                                eta_discharge=0.95,
                                dt_h=0.5,
                                terminal_mode="exact",
                                mode="network_lp",
                            )
                            rows.append({
                                "date": str(r.date), "day_index": int(r.day_index), "group": int(r.group), "site": str(r.site),
                                "initial_soc": initial_soc, "terminal_soc": terminal_soc, "capacity_kwh": capacity_kwh,
                                "second_start": second_start, "second_gap_h": (second_start - (8 + duration)) * 0.5,
                                "service_duration_h": duration * 0.5, "service_power_kw": float(result.service_kw),
                                "planner_feasible": int(result.feasible),
                            })
    frame = pd.DataFrame(rows)
    summary = frame.groupby(["initial_soc", "terminal_soc", "capacity_kwh", "second_start", "service_duration_h"], as_index=False).agg(
        n=("service_power_kw", "size"), mean_service_power_kw=("service_power_kw", "mean"),
        p05_service_power_kw=("service_power_kw", lambda x: float(x.quantile(0.05))),
        min_service_power_kw=("service_power_kw", "min"), planner_failure_count=("planner_feasible", lambda x: int((x == 0).sum())),
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / "contract_parameter_rows.csv", index=False)
    summary.to_csv(out_dir / "contract_parameter_summary.csv", index=False)
    metadata = {
        "status": "contract_parameter_sensitivity_round1",
        "sample": "10 spread dates x 2 groups x 2 primary sites = 40 baseline-gated units",
        "variants": {"initial_soc": [0.6, 0.8], "terminal_soc": [0.6, 0.8], "capacity_kwh": [500, 1000, 2000], "second_start": [20, 24], "service_duration_intervals": [4, 6]},
        "contract": "two-call exact-terminal scalar AC-bound LP; recovery is only between and after service windows",
        "replay_scope": "none; uses frozen audited scalar bounds",
        "seed": 20261003,
        "rows": int(len(frame)),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (out_dir / "README.md").write_text(
        "# Contract parameter sensitivity round 1\n\n"
        "A balanced 40-unit scalar-bound audit varying initial/terminal SOC, capacity, "
        "second-call separation, and service-window length. Results are descriptive "
        "contract sensitivities under frozen audited AC bounds, not nonlinear replay or "
        "population estimates.\n"
    )
    return metadata


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", type=Path, default=DEFAULT_BOUNDS)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    print(json.dumps(run(args.bounds, args.policy, args.out_dir), indent=2))
