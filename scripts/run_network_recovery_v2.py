#!/usr/bin/env python3
"""Network-aware repeated-service contract experiment (fair-window protocol).

This protocol extends the horizon beyond the second service call so every
policy has a declared opportunity to restore the terminal SOC.  The static
recovery baseline is charged only in the two inter-call/post-call windows;
the myopic policy greedily targets the next call and then the terminal SOC.
The AC-bound scalar LP sees the full chronological horizon and uses
AC-audited interval limits.
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
from recoveryflex.dispatch import plan_service
import run_corrected_experiment as exp
from recoveryflex.profile_bank import load_bank


SITES = ("611.3", "634.1")
METHODS = ("network_lp", "fixed_recovery", "myopic_recovery", "energy_only")
P_GRID = np.arange(0.0, 301.0, 20.0)
HORIZON_INTERVALS = 48
AC_CONSTRAINT_TOLERANCE = 1e-6
WINDOWS = ((8, 12), (24, 28))
FIXED_RECOVERY_WINDOWS = ((12, 24), (28, 48))
FIXED_RECOVERY_INTERVALS = sum(b - a for a, b in FIXED_RECOVERY_WINDOWS)
SERVICE_INTERVALS_TOTAL = sum(b - a for a, b in WINDOWS)
SERVICE_HOURS = SERVICE_INTERVALS_TOTAL * exp.DT_H
RECOVERY_HOURS = FIXED_RECOVERY_INTERVALS * exp.DT_H
# Match the battery-side energy removed during all service intervals:
# eta_c * (r P) * RECOVERY_HOURS = (P / eta_d) * SERVICE_HOURS.
# Thus r is the AC-side recovery-charge kW divided by service-export kW.
REARM_RATIO = SERVICE_HOURS / (
    RECOVERY_HOURS * exp.ETA_CHARGE * exp.ETA_DISCHARGE
)
BATTERY_ENERGY_KWH = 2000.0


def _bounds(feeder, load_day, pv_day, site):
    def max_feasible(load_value, pv_value, sign):
        """Find the largest feasible magnitude with a checked monotone search.

        The largest feasible prefix of a checked coarse grid brackets the
        transition and eight bisection steps refine it to below 0.1 kW. A
        later feasible point after a gap is ignored, so a non-monotone AC
        response cannot silently become an interval upper bound.
        """
        feasible = []
        for p in P_GRID:
            a = feeder.solve(float(load_value), float(pv_value), {site: float(sign * p)})
            feasible.append(bool(a.feasible))
        true_idx = [i for i, ok in enumerate(feasible) if ok]
        zero_ok = bool(feasible[0])
        if not true_idx or not zero_ok:
            return 0.0, False, zero_ok
        # Use the largest *prefix* of the checked grid.  A later feasible
        # point after a gap is not treated as an interval bound; this keeps
        # the reduced model conservative when AC feasibility is non-monotone.
        last = 0
        while last + 1 < len(feasible) and feasible[last + 1]:
            last += 1
        if last == len(P_GRID) - 1:
            lo, hi = float(P_GRID[last]), 300.0
        else:
            lo, hi = float(P_GRID[last]), float(P_GRID[last + 1])
        for _ in range(8):
            mid = 0.5 * (lo + hi)
            a = feeder.solve(float(load_value), float(pv_value), {site: float(sign * mid)})
            if a.feasible:
                lo = mid
            else:
                hi = mid
        return lo, True, zero_ok

    n = load_day.size
    export = np.zeros(n)
    charge = np.zeros(n)
    reasons = []
    for t in range(n):
        export[t], exp_ok, exp_zero_ok = max_feasible(load_day[t], pv_day[t], 1.0)
        charge[t], ch_ok, ch_zero_ok = max_feasible(load_day[t], pv_day[t], -1.0)
        if not exp_ok:
            reasons.append((t, "export"))
        if not ch_ok:
            reasons.append((t, "charge"))
        if not exp_zero_ok:
            reasons.append((t, "baseline_export"))
        if not ch_zero_ok:
            reasons.append((t, "baseline_charge"))
    return charge, export, reasons


def _replay(feeder, load_day, pv_day, site, result):
    audits = []
    for l, p, ch, dis in zip(
        load_day, pv_day, result.charge_kw, result.discharge_kw
    ):
        audits.append(feeder.solve(float(l), float(p), {site: float(dis - ch)}))
    return bool(result.feasible and all(a.feasible for a in audits)), audits


def _embedded_external(dev, source):
    x = np.load(source, allow_pickle=False)
    load = np.transpose(x["load_kw"], (0, 2, 1))
    pv = np.transpose(x["pv_kw"], (0, 2, 1))
    load = np.clip(
        exp.LOAD_OFFSET
        + exp.LOAD_GAIN * load / dev.train_load_scale_kw[None, None, :],
        0.35,
        0.85,
    )
    pv = np.clip(
        exp.PV_OFFSET
        + exp.PV_GAIN * pv / dev.train_pv_scale_kw[None, None, :],
        0.0,
        1.0,
    )
    return load, pv, x["dates"].astype(str)


def run(
    max_days: int = 12,
    groups: int = 10,
    out_dir: Path = ROOT / "results" / "network_recovery_v2_dev",
    source: Path = ROOT / "data" / "processed" / "ausgrid_external_2012_2013_strict.npz",
    day_start: int = 0,
    day_end: int | None = None,
    cached_bounds: Path | None = None,
    cached_audit: Path | None = None,
    normalizer_bank: Path | None = None,
):
    dev = load_bank(normalizer_bank or exp.BANK_PATH)
    load, pv, dates = _embedded_external(dev, source)
    start = max(0, int(day_start))
    stop = min(load.shape[0], int(day_end) if day_end is not None else start + max_days)
    if stop <= start:
        raise ValueError("day_end must be greater than day_start")
    nday = stop - start
    ng = min(groups, load.shape[2])
    bound_cache = None
    audit_cache = None
    if cached_bounds is not None:
        bound_cache = pd.read_csv(cached_bounds)
        bound_cache["site"] = bound_cache["site"].astype(str)
        audit_path = cached_audit or (cached_bounds.parent / "baseline_zero_audit.csv")
        audit_frame = pd.read_csv(audit_path)
        audit_frame["site"] = audit_frame["site"].astype(str)
        audit_cache = {
            (str(r.date), int(r.group), str(r.site)): int(r.baseline_zero_feasible)
            for r in audit_frame.itertuples()
        }
    rows = []
    bound_rows = []
    trace_rows = []
    fixed_windows = FIXED_RECOVERY_WINDOWS
    for site in SITES:
        feeder = ACSnapshotFeeder(
            exp.FEEDER_PATH,
            battery_sites=(site,),
            pv_sites={"675.1": exp.PV_RATED_KW},
            voltage_limits=exp.VOLTAGE_LIMITS,
            line_loading_limit=exp.LINE_LIMIT,
            constraint_tolerance=AC_CONSTRAINT_TOLERANCE,
        )
        for day in range(start, stop):
            for group in range(ng):
                ld = load[day, :HORIZON_INTERVALS, group]
                pd_ = pv[day, :HORIZON_INTERVALS, group]
                if bound_cache is None:
                    charge, export, reasons = _bounds(feeder, ld, pd_, site)
                    baseline_feasible = int(len(reasons) == 0)
                else:
                    cached = bound_cache[
                        (bound_cache.date.astype(str) == str(dates[day]))
                        & (bound_cache.day_index == day)
                        & (bound_cache.group == group)
                        & (bound_cache.site == str(site))
                    ].sort_values("interval")
                    if len(cached) != HORIZON_INTERVALS:
                        raise ValueError(f"cached bounds missing {dates[day]}/{group}/{site}")
                    charge = cached.charge_limit_kw.to_numpy(float)
                    export = cached.export_limit_kw.to_numpy(float)
                    baseline_feasible = audit_cache[(str(dates[day]), group, str(site))]
                for t in range(HORIZON_INTERVALS):
                    bound_rows.append(
                        {
                            "date": dates[day],
                            "day_index": day,
                            "group": group,
                            "site": site,
                            "interval": t,
                            "charge_limit_kw": charge[t],
                            "export_limit_kw": export[t],
                        }
                    )
                common = dict(
                    charge_limit_kw=charge,
                    export_limit_kw=export,
                    load_kw=ld,
                    service_windows=WINDOWS,
                    energy_kwh=BATTERY_ENERGY_KWH,
                    initial_soc=exp.SOC_INITIAL,
                    terminal_soc_target=exp.SOC_INITIAL,
                    soc_min=exp.SOC_RESERVE,
                    soc_max=1.0,
                    eta_charge=exp.ETA_CHARGE,
                    eta_discharge=exp.ETA_DISCHARGE,
                    dt_h=exp.DT_H,
                    terminal_mode="exact",
                    # The contract permits recovery only after a service
                    # call. Passing the mask to every method prevents the
                    # network and energy-only counterfactuals from silently
                    # pre-charging before the first call.
                    recovery_windows=fixed_windows,
                )
                modes = {
                    "network_lp": dict(mode="network_lp"),
                    "fixed_recovery": dict(
                        mode="fixed_recovery",
                        fixed_recovery_ratio=REARM_RATIO,
                    ),
                    "myopic_recovery": dict(mode="myopic_recovery"),
                    "energy_only": dict(mode="energy_only"),
                }
                for method, kw in modes.items():
                    result = plan_service(**common, **kw)
                    replay_ok, audits = _replay(feeder, ld, pd_, site, result)
                    rows.append(
                        {
                            "date": dates[day],
                            "day_index": day,
                            "group": group,
                            "site": site,
                            "method": method,
                            "service_kw": result.service_kw,
                            "planner_feasible": int(result.feasible),
                            "replay_feasible": int(replay_ok),
                            "baseline_feasible": baseline_feasible,
                            "terminal_soc": result.terminal_soc,
                            "max_vmax": max(
                                (a.vmax for a in audits if np.isfinite(a.vmax)),
                                default=np.nan,
                            ),
                            "max_loading": max(
                                (
                                    a.max_line_loading
                                    for a in audits
                                    if np.isfinite(a.max_line_loading)
                                ),
                                default=np.nan,
                            ),
                            "message": result.message,
                        }
                    )
                    if day == start and group == 0 and site == SITES[0]:
                        trace_rows.extend(
                            {
                                "interval": t,
                                "method": method,
                                "charge_kw": result.charge_kw[t],
                                "discharge_kw": result.discharge_kw[t],
                                "soc": result.soc[t],
                                "grid_import_kw": result.grid_import_kw[t],
                                "charge_limit_kw": charge[t],
                                "export_limit_kw": export[t],
                            }
                            for t in range(len(ld))
                        )
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out_dir / "policy_rows.csv", index=False)
    pd.DataFrame(bound_rows).to_csv(out_dir / "ac_bounds.csv", index=False)
    pd.DataFrame(trace_rows).to_csv(out_dir / "representative_trace.csv", index=False)
    grouped = df.groupby(["site", "method"], as_index=False).agg(
        mean_service_kw=("service_kw", "mean"),
        replay_success=("replay_feasible", "mean"),
        baseline_success=("baseline_feasible", "mean"),
        n=("service_kw", "size"),
    )
    conditional = (
        df[df.baseline_feasible == 1]
        .groupby(["site", "method"], as_index=False)
        .agg(
            conditional_replay_success=("replay_feasible", "mean"),
            conditional_mean_service_kw=("service_kw", "mean"),
            n_baseline=("service_kw", "size"),
        )
    )
    summary = {
        "status": "network_recovery_v2",
        "source": str(source),
        "n_days": nday,
        "day_start": start,
        "day_end": stop,
        "n_groups": ng,
        "battery_energy_kwh": BATTERY_ENERGY_KWH,
        "horizon_intervals": HORIZON_INTERVALS,
        "service_windows": [list(x) for x in WINDOWS],
        "fixed_recovery_windows": [list(x) for x in FIXED_RECOVERY_WINDOWS],
        "fixed_recovery_ratio": REARM_RATIO,
        "service_hours": SERVICE_HOURS,
        "recovery_hours": RECOVERY_HOURS,
        "coarse_grid": {
            "lower_kw": float(P_GRID[0]),
            "upper_kw": float(P_GRID[-1]),
            "step_kw": float(P_GRID[1] - P_GRID[0]),
            "n_points": int(P_GRID.size),
            "prefix_bisection_iterations": 8,
            "maximum_refinement_width_kw": float((P_GRID[1] - P_GRID[0]) / 2**8),
            "interpretation": "checked-prefix endpoint; later feasible points after a gap are ignored",
        },
        "ac_constraint_tolerance": AC_CONSTRAINT_TOLERANCE,
        "summary": grouped.to_dict(orient="records"),
        "conditional_summary": conditional.to_dict(orient="records"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-days", type=int, default=12)
    ap.add_argument("--groups", type=int, default=10)
    ap.add_argument("--day-start", type=int, default=0)
    ap.add_argument("--day-end", type=int, default=None)
    ap.add_argument("--sites", type=str, default=",".join(SITES), help="comma-separated IEEE13 battery placements")
    ap.add_argument("--cached-bounds", type=Path, default=None,
                    help="reuse an existing AC-bound table and rerun only dispatch/replay")
    ap.add_argument("--cached-audit", type=Path, default=None,
                    help="baseline-zero audit paired with --cached-bounds")
    ap.add_argument("--normalizer-bank", type=Path, default=None,
                    help="profile bank whose train split supplies normalization scales")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "results" / "network_recovery_v2_dev")
    ap.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    args = ap.parse_args()
    SITES = tuple(s.strip() for s in args.sites.split(",") if s.strip())
    print(json.dumps(run(args.max_days, args.groups, args.out_dir, args.source, args.day_start, args.day_end,
                         args.cached_bounds, args.cached_audit, args.normalizer_bank), indent=2))
