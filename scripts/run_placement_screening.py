#!/usr/bin/env python3
"""Lightweight, predeclared placement screening for the IEEE-13 snapshot.

This is a diagnostic sensitivity and does not overwrite the strict-v4
two-placement experiment.  It evaluates instantaneous AC export/charge
prefix bounds at a small, calendar-stratified set of external profiles.
The output must not be interpreted as a repeated-service contract estimate:
no SOC dispatch, bootstrap, or full-year replay is performed here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from recoveryflex.ac_snapshot import ACSnapshotFeeder
import run_corrected_experiment as exp
from recoveryflex.profile_bank import load_bank


HORIZON_INTERVALS = 48
SERVICE_INTERVALS = tuple(range(8, 12)) + tuple(range(24, 28))
# Four short recovery slices are sampled to show whether placement headroom
# is concentrated in one part of either recovery window.
RECOVERY_INTERVALS = tuple(range(12, 16)) + tuple(range(20, 24)) + tuple(range(28, 32)) + tuple(range(40, 44))
P_GRID = np.arange(0.0, 301.0, 20.0)
VOLTAGE_LIMITS = exp.VOLTAGE_LIMITS
LINE_LIMIT = exp.LINE_LIMIT
PV_SITE = "675.1"


def _all_candidate_sites() -> list[str]:
    """Enumerate every modeled non-source bus phase from the snapshot."""
    feeder = ACSnapshotFeeder(
        exp.FEEDER_PATH,
        battery_sites=(),
        pv_sites={PV_SITE: exp.PV_RATED_KW},
        voltage_limits=VOLTAGE_LIMITS,
        line_loading_limit=LINE_LIMIT,
    )
    out: list[str] = []
    for raw in feeder.dss.Circuit.AllBusNames():
        bus = str(raw)
        if bus.casefold() == "sourcebus":
            continue
        feeder.dss.Circuit.SetActiveBus(bus)
        for node in feeder.dss.Bus.Nodes():
            out.append(f"{bus}.{int(node)}")
    return out


def _sample_days(dates: np.ndarray) -> list[int]:
    """Choose the first and last retained date in each contiguous block."""
    date_values = pd.to_datetime(dates)
    blocks: list[list[int]] = []
    current = [0]
    for i in range(1, len(date_values)):
        if date_values[i] - date_values[i - 1] != pd.Timedelta(days=1):
            blocks.append(current)
            current = [i]
        else:
            current.append(i)
    if current:
        blocks.append(current)
    # Include one date from each block's endpoints, preserving chronology.
    chosen: list[int] = []
    for block in blocks:
        chosen.extend([block[0], block[-1]])
    return list(dict.fromkeys(chosen))


def _max_prefix(feeder: ACSnapshotFeeder, load: float, pv: float, site: str, sign: float) -> tuple[float, bool]:
    """Return a checked-grid prefix bound and whether zero power is feasible."""
    feasible = []
    for p in P_GRID:
        audit = feeder.solve(load, pv, {site: float(sign * p)})
        feasible.append(bool(audit.feasible))
    if not feasible[0]:
        return 0.0, False
    last = 0
    while last + 1 < len(feasible) and feasible[last + 1]:
        last += 1
    if last == len(P_GRID) - 1:
        # The screen is deliberately capped at the same 300 kW command grid
        # used by the main protocol; do not imply an unbounded AC result.
        return float(P_GRID[-1]), True
    lo = float(P_GRID[last])
    hi = float(P_GRID[last + 1])
    for _ in range(8):
        mid = 0.5 * (lo + hi)
        if feeder.solve(load, pv, {site: float(sign * mid)}).feasible:
            lo = mid
        else:
            hi = mid
    return lo, True


def run(
    source: Path,
    out_dir: Path,
    sites: list[str] | None = None,
    groups: tuple[int, ...] = (0, 5),
) -> dict:
    dev = load_bank(exp.BANK_PATH)
    x = np.load(source, allow_pickle=False)
    load = np.transpose(x["load_kw"], (0, 2, 1))
    pv = np.transpose(x["pv_kw"], (0, 2, 1))
    dates = x["dates"].astype(str)
    load = np.clip(exp.LOAD_OFFSET + exp.LOAD_GAIN * load / dev.train_load_scale_kw[None, None, :], 0.35, 0.85)
    pv = np.clip(exp.PV_OFFSET + exp.PV_GAIN * pv / dev.train_pv_scale_kw[None, None, :], 0.0, 1.0)
    days = _sample_days(dates)
    site_list = list(sites or _all_candidate_sites())
    rows: list[dict] = []
    for site in site_list:
        feeder = ACSnapshotFeeder(
            exp.FEEDER_PATH,
            battery_sites=(site,),
            pv_sites={PV_SITE: exp.PV_RATED_KW},
            voltage_limits=VOLTAGE_LIMITS,
            line_loading_limit=LINE_LIMIT,
        )
        for day in days:
            for group in groups:
                service_export: list[float] = []
                recovery_charge: list[float] = []
                baseline_ok = True
                baseline_reasons: list[str] = []
                for t in sorted(set(SERVICE_INTERVALS + RECOVERY_INTERVALS)):
                    # The zero-power gate is evaluated at every sampled point;
                    # a failure is retained as a diagnostic rather than
                    # silently dropped from the placement ranking.
                    zero = feeder.solve(float(load[day, t, group]), float(pv[day, t, group]), {site: 0.0})
                    if not zero.feasible:
                        baseline_ok = False
                        baseline_reasons.append(f"{t}:{zero.limiting_component or zero.error}")
                    export, _ = _max_prefix(feeder, float(load[day, t, group]), float(pv[day, t, group]), site, 1.0)
                    charge, _ = _max_prefix(feeder, float(load[day, t, group]), float(pv[day, t, group]), site, -1.0)
                    if t in SERVICE_INTERVALS:
                        service_export.append(export)
                    else:
                        recovery_charge.append(charge)
                rows.append({
                    "date": str(dates[day]),
                    "day_index": int(day),
                    "group": int(group),
                    "site": site,
                    "sampled_baseline_ok": int(baseline_ok),
                    "baseline_reasons": " | ".join(baseline_reasons[:4]),
                    "service_min_export_kw": float(np.min(service_export)),
                    "service_mean_export_kw": float(np.mean(service_export)),
                    "recovery_min_charge_kw": float(np.min(recovery_charge)),
                    "recovery_mean_charge_kw": float(np.mean(recovery_charge)),
                    "n_service_intervals": len(service_export),
                    "n_recovery_intervals": len(recovery_charge),
                })
    frame = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / "placement_profile_rows.csv", index=False)
    summary = (
        frame.groupby("site", as_index=False)
        .agg(
            n_profiles=("site", "size"),
            sampled_baseline_rate=("sampled_baseline_ok", "mean"),
            p10_service_min_export_kw=("service_min_export_kw", lambda x: float(np.quantile(x, 0.10))),
            median_service_min_export_kw=("service_min_export_kw", "median"),
            p90_service_min_export_kw=("service_min_export_kw", lambda x: float(np.quantile(x, 0.90))),
            p10_recovery_min_charge_kw=("recovery_min_charge_kw", lambda x: float(np.quantile(x, 0.10))),
            median_recovery_min_charge_kw=("recovery_min_charge_kw", "median"),
            p90_recovery_min_charge_kw=("recovery_min_charge_kw", lambda x: float(np.quantile(x, 0.90))),
        )
        .sort_values(["p10_service_min_export_kw", "median_service_min_export_kw"], ascending=False)
    )
    summary.to_csv(out_dir / "placement_summary.csv", index=False)
    metadata = {
        "status": "diagnostic_placement_screening",
        "source": str(source),
        "sites": site_list,
        "n_sites": len(site_list),
        "sampled_days": [int(i) for i in days],
        "sampled_dates": [str(dates[i]) for i in days],
        "groups": [int(g) for g in groups],
        "service_intervals": list(SERVICE_INTERVALS),
        "recovery_intervals": list(RECOVERY_INTERVALS),
        "grid_kw": P_GRID.tolist(),
        "bound_method": "largest feasible prefix on 0--300 kW grid with 8 bisection steps; no SOC dispatch or full-year replay",
        "warning": "diagnostic placement screening only; not a repeated-service contract estimate and not part of strict-v4 primary results",
    }
    (out_dir / "summary.json").write_text(json.dumps(metadata, indent=2))
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/placement_screening_strict_v4")
    parser.add_argument("--sites", type=str, default="", help="comma-separated sites; empty enumerates all modeled non-source phases")
    parser.add_argument("--groups", type=str, default="0,5")
    args = parser.parse_args()
    sites = [x.strip() for x in args.sites.split(",") if x.strip()] or None
    groups = tuple(int(x) for x in args.groups.split(",") if x.strip())
    print(json.dumps(run(args.source, args.out_dir, sites, groups), indent=2))
