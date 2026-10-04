#!/usr/bin/env python3
"""Evidence audit for the outstanding scope and numerical caveats.

This is an audit companion, not a replacement for the frozen strict-v4
experiment.  It deliberately labels sample-only AC replays, scalar-bound
device caps, and embedding sweeps as diagnostics.  No extra feeder or field
data are introduced.
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

import run_corrected_experiment as exp
import run_network_recovery_v2 as protocol
from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.dispatch import plan_service
from recoveryflex.profile_bank import load_bank


SITES = ("611.3", "634.1")
GRID = np.arange(0.0, 301.0, 20.0)
WINDOWS = protocol.WINDOWS
RECOVERY = protocol.FIXED_RECOVERY_WINDOWS
DT = exp.DT_H


def embed(raw: Path, load_gain: float = exp.LOAD_GAIN,
          pv_gain: float = exp.PV_GAIN, pv_rated: float = exp.PV_RATED_KW):
    bank = load_bank(exp.BANK_PATH)
    x = np.load(raw, allow_pickle=False)
    load = np.transpose(x["load_kw"], (0, 2, 1))
    pv = np.transpose(x["pv_kw"], (0, 2, 1))
    load = np.clip(exp.LOAD_OFFSET + load_gain * load / bank.train_load_scale_kw[None, None, :], 0.35, 0.85)
    pv = np.clip(exp.PV_OFFSET + pv_gain * pv / bank.train_pv_scale_kw[None, None, :], 0.0, 1.0)
    return load, pv, x["dates"].astype(str), float(pv_rated)


def feeder(site: str, *, tol: float = 1e-6, command_tol: float = 1e-2,
           pv_site: str = "675.1", pv_rated: float = exp.PV_RATED_KW) -> ACSnapshotFeeder:
    return ACSnapshotFeeder(
        exp.FEEDER_PATH, battery_sites=(str(site),),
        pv_sites={str(pv_site): float(pv_rated)},
        voltage_limits=exp.VOLTAGE_LIMITS,
        line_loading_limit=exp.LINE_LIMIT,
        command_tolerance_kw=float(command_tol),
        constraint_tolerance=float(tol),
    )


def prefix(feeder_obj: ACSnapshotFeeder, load: float, pv: float, site: str,
           sign: float, grid: np.ndarray = GRID) -> tuple[float, list[bool]]:
    flags = [bool(feeder_obj.solve(float(load), float(pv), {site: float(sign * p)}).feasible) for p in grid]
    if not flags or not flags[0]:
        return 0.0, flags
    last = 0
    while last + 1 < len(flags) and flags[last + 1]:
        last += 1
    if last == len(grid) - 1:
        return float(grid[-1]), flags
    lo, hi = float(grid[last]), float(grid[last + 1])
    for _ in range(8):
        mid = (lo + hi) / 2.0
        if feeder_obj.solve(float(load), float(pv), {site: float(sign * mid)}).feasible:
            lo = mid
        else:
            hi = mid
    return float(lo), flags


def main_dispatch(charge: np.ndarray, export: np.ndarray, load: np.ndarray,
                  *, service_power: float | None = None):
    kw = dict(
        charge_limit_kw=charge, export_limit_kw=export, load_kw=load,
        service_windows=WINDOWS, recovery_windows=RECOVERY,
        energy_kwh=protocol.BATTERY_ENERGY_KWH, initial_soc=exp.SOC_INITIAL,
        terminal_soc_target=exp.SOC_INITIAL, soc_min=exp.SOC_RESERVE, soc_max=1.0,
        eta_charge=exp.ETA_CHARGE, eta_discharge=exp.ETA_DISCHARGE,
        dt_h=exp.DT_H, terminal_mode="exact", mode="network_lp",
    )
    if service_power is not None:
        kw["service_power_kw"] = float(service_power)
    return plan_service(**kw)


def replay_ok(feeder_obj: ACSnapshotFeeder, load: np.ndarray, pv: np.ndarray,
              site: str, result) -> tuple[bool, list]:
    audits = [feeder_obj.solve(float(l), float(v), {site: float(d - c)})
              for l, v, c, d in zip(load, pv, result.charge_kw, result.discharge_kw)]
    return bool(result.feasible and all(a.feasible for a in audits)), audits


def sample_units(gate: pd.DataFrame, n_dates: int = 10) -> pd.DataFrame:
    days = np.unique(np.linspace(0, int(gate.day_index.max()), n_dates, dtype=int))
    out = gate[gate.day_index.isin(days) & (gate.baseline_zero_feasible.astype(int) == 1)].copy()
    # Keep a deterministic, balanced 10-group cross-section per date/site.
    out = out.sort_values(["site", "day_index", "group"]).groupby(["site", "day_index"], as_index=False).head(10)
    return out.reset_index(drop=True)


def audit_replay_and_prefix(raw: Path, primary: Path, out: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    load, pv, dates, _ = embed(raw)
    gate = pd.read_csv(primary / "baseline_zero_audit.csv")
    gate["site"] = gate.site.astype(str)
    units = sample_units(gate)
    bounds = pd.read_csv(primary / "ac_bounds.csv")
    bounds["site"] = bounds.site.astype(str)
    rows, prefix_rows = [], []
    for site in SITES:
        f = feeder(site)
        for u in units[units.site == site].itertuples(index=False):
            day, g = int(u.day_index), int(u.group)
            ld, pv_d = load[day, :48, g], pv[day, :48, g]
            b = bounds[(bounds.site == site) & (bounds.day_index == day) & (bounds.group == g)].sort_values("interval")
            charge, export = b.charge_limit_kw.to_numpy(float), b.export_limit_kw.to_numpy(float)
            lp = main_dispatch(charge, export, ld)
            f_ok, f_audits = replay_ok(f, ld, pv_d, site, lp)
            # The scalar endpoint itself is explicitly tested first.  If it
            # passes, the nonlinear replay endpoint is at least that large
            # and the scalar-vs-replay gap is zero for this audit.  Only a
            # failing scalar endpoint triggers a lower-power search; starting
            # with lo=0 and seven iterations would otherwise report a
            # purely algorithmic ~1/128 under-estimate even when every
            # tested endpoint passed.
            if f_ok:
                lo = float(lp.service_kw)
            else:
                lo, hi = 0.0, float(lp.service_kw)
                for _ in range(12):
                    mid = (lo + hi) / 2.0
                    candidate = main_dispatch(charge, export, ld, service_power=mid)
                    ok, _ = replay_ok(f, ld, pv_d, site, candidate)
                    if ok:
                        lo = mid
                    else:
                        hi = mid
            rows.append({
                "date": str(dates[day]), "day_index": day, "group": g, "site": site,
                "scalar_endpoint_kw": float(lp.service_kw), "replay_endpoint_checked_kw": float(lo),
                "scalar_minus_replay_kw": float(lp.service_kw - lo),
                "replay_at_scalar": int(f_ok),
                "max_vmax_at_scalar": float(max(a.vmax for a in f_audits if np.isfinite(a.vmax))),
                "max_loading_at_scalar": float(max(a.max_line_loading for a in f_audits if np.isfinite(a.max_line_loading))),
            })
            # Full checked coarse grid at every interval and both directions.
            for t, (l, v) in enumerate(zip(ld, pv_d)):
                for sign, direction in ((1.0, "export"), (-1.0, "charge")):
                    _, flags = prefix(f, float(l), float(v), site, sign)
                    later_after_failure = any(flags[i - 1] is False and flags[i] is True for i in range(1, len(flags)))
                    prefix_rows.append({
                        "date": str(dates[day]), "day_index": day, "group": g, "site": site,
                        "interval": t, "direction": direction,
                        "zero_feasible": int(flags[0]), "grid_feasible_pattern": "".join("1" if x else "0" for x in flags),
                        "later_feasible_after_failure": int(later_after_failure),
                    })
    replay = pd.DataFrame(rows)
    pref = pd.DataFrame(prefix_rows)
    replay.to_csv(out / "scalar_vs_replay_sample.csv", index=False)
    pref.to_csv(out / "prefix_monotonicity_sample.csv", index=False)
    return replay, pref


def audit_tolerances(raw: Path, primary: Path, out: Path) -> pd.DataFrame:
    load, pv, dates, _ = embed(raw)
    gate = pd.read_csv(primary / "baseline_zero_audit.csv")
    gate.site = gate.site.astype(str)
    units = sample_units(gate, n_dates=2)  # 20 units per site, enough for numerical audit.
    rows = []
    for site in SITES:
        for tol in (0.0, 1e-6, 1e-5):
            for command_tol in (0.0, 1e-2):
                f = feeder(site, tol=tol, command_tol=command_tol)
                for u in units[units.site == site].itertuples(index=False):
                    day, g = int(u.day_index), int(u.group)
                    ld, pv_d = load[day, :48, g], pv[day, :48, g]
                    for grid_step in (10.0, 20.0, 40.0):
                        grid = np.arange(0.0, 300.0 + grid_step / 2.0, grid_step)
                        ex, ch = [], []
                        for l, v in zip(ld, pv_d):
                            e, _ = prefix(f, float(l), float(v), site, 1.0, grid)
                            c, _ = prefix(f, float(l), float(v), site, -1.0, grid)
                            ex.append(e); ch.append(c)
                        lp = main_dispatch(np.asarray(ch), np.asarray(ex), ld)
                        rows.append({
                            "site": site, "day_index": day, "group": g,
                            "constraint_tolerance": tol, "command_tolerance_kw": command_tol,
                            "grid_step_kw": grid_step, "service_endpoint_kw": float(lp.service_kw),
                        })
    frame = pd.DataFrame(rows)
    frame.to_csv(out / "numerical_sensitivity_sample.csv", index=False)
    return frame


def audit_device_caps(primary: Path, out: Path) -> pd.DataFrame:
    bounds = pd.read_csv(primary / "ac_bounds.csv")
    bounds.site = bounds.site.astype(str)
    rows = []
    for (site, day, group), b in bounds.groupby(["site", "day_index", "group"], sort=False):
        b = b.sort_values("interval")
        load = np.zeros(48)  # only the service/export and recovery caps affect P; load is unused by LP constraints.
        for cap in (80.0, 100.0, 150.0, 200.0, 300.0):
            charge = np.minimum(b.charge_limit_kw.to_numpy(float), cap)
            export = np.minimum(b.export_limit_kw.to_numpy(float), cap)
            result = main_dispatch(charge, export, load)
            rows.append({"site": site, "day_index": int(day), "group": int(group), "power_cap_kw": cap,
                         "service_endpoint_kw": float(result.service_kw), "planner_feasible": int(result.feasible)})
    frame = pd.DataFrame(rows)
    summary = frame.groupby(["site", "power_cap_kw"], as_index=False).agg(
        n=("service_endpoint_kw", "size"), mean_endpoint_kw=("service_endpoint_kw", "mean"),
        p05_endpoint_kw=("service_endpoint_kw", lambda x: float(x.quantile(.05))),
        p95_endpoint_kw=("service_endpoint_kw", lambda x: float(x.quantile(.95))),
    )
    frame.to_csv(out / "device_power_cap_rows.csv", index=False)
    summary.to_csv(out / "device_power_cap_summary.csv", index=False)
    return summary


def audit_embedding(raw: Path, out: Path) -> pd.DataFrame:
    variants = [
        ("base", exp.LOAD_GAIN, exp.PV_GAIN, exp.PV_RATED_KW, "675.1"),
        ("higher_load_gain", 0.45, exp.PV_GAIN, exp.PV_RATED_KW, "675.1"),
        ("lower_pv_rating", exp.LOAD_GAIN, exp.PV_GAIN, 150.0, "675.1"),
        ("higher_pv_rating", exp.LOAD_GAIN, exp.PV_GAIN, 450.0, "675.1"),
        ("pv_at_634.1", exp.LOAD_GAIN, exp.PV_GAIN, exp.PV_RATED_KW, "634.1"),
    ]
    days = (0, 102, 103, 127, 128, 218)
    groups = (0, 5)
    rows = []
    for name, lg, pg, rated, pv_site in variants:
        load, pv, dates, _ = embed(raw, load_gain=lg, pv_gain=pg, pv_rated=rated)
        for site in SITES:
            f = feeder(site, pv_site=pv_site, pv_rated=rated)
            for day in days:
                for g in groups:
                    ex, ch = [], []
                    for l, v in zip(load[day, :48, g], pv[day, :48, g]):
                        e, _ = prefix(f, float(l), float(v), site, 1.0)
                        c, _ = prefix(f, float(l), float(v), site, -1.0)
                        ex.append(e); ch.append(c)
                    result = main_dispatch(np.asarray(ch), np.asarray(ex), load[day, :48, g])
                    rows.append({"variant": name, "load_gain": lg, "pv_gain": pg, "pv_rated_kw": rated,
                                 "pv_site": pv_site, "site": site, "date": dates[day], "group": g,
                                 "service_endpoint_kw": float(result.service_kw), "planner_feasible": int(result.feasible)})
    frame = pd.DataFrame(rows)
    frame.to_csv(out / "embedding_sensitivity_rows.csv", index=False)
    summary = frame.groupby(["variant", "site"], as_index=False).agg(
        n=("service_endpoint_kw", "size"), mean_endpoint_kw=("service_endpoint_kw", "mean"),
        p05_endpoint_kw=("service_endpoint_kw", lambda x: float(x.quantile(.05))),
        p95_endpoint_kw=("service_endpoint_kw", lambda x: float(x.quantile(.95))),
    )
    summary.to_csv(out / "embedding_sensitivity_summary.csv", index=False)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", type=Path, default=ROOT / "results/network_recovery_external_2012_2013_strict_v4")
    ap.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    ap.add_argument("--out", type=Path, default=ROOT / "results/ac_coverage_audit_round1")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    gate = pd.read_csv(args.primary / "baseline_zero_audit.csv")
    gate.site = gate.site.astype(str)
    policy = pd.read_csv(args.primary / "policy_rows.csv")
    policy.site = policy.site.astype(str)
    unconditional = policy.groupby(["site", "method"], as_index=False).agg(
        n=("service_kw", "size"), gate_pass=("baseline_feasible", "sum"),
        planner_success=("planner_feasible", "sum"), replay_success=("replay_feasible", "sum"),
        unconditional_replay_rate=("replay_feasible", "mean"),
    )
    unconditional.to_csv(args.out / "unconditional_gate_summary.csv", index=False)
    replay, pref = audit_replay_and_prefix(args.source, args.primary, args.out)
    numerical = audit_tolerances(args.source, args.primary, args.out)
    device = audit_device_caps(args.primary, args.out)
    embedding = audit_embedding(args.source, args.out)
    metadata = {
        "status": "ac_coverage_audit_round1",
        "primary_results": str(args.primary.resolve()),
        "scope": {
            "replay_endpoint": "200 baseline-gated units (10 dates x 10 groups x 2 sites); scalar endpoint is tested first and any failing endpoint receives a 12-step lower-power search; sample diagnostic only",
            "prefix": "same sample, all 48 intervals and both signs on 0--300 kW at 20 kW grid; later-feasible-after-failure is explicitly counted",
            "numerical": "40 units (2 dates x 10 groups x 2 sites), tol 0/1e-6/1e-5, command readback floor 0/0.01 kW, grid steps 10/20/40 kW",
            "device": "all 4,380 primary units, frozen scalar-bound dispatch with symmetric added power caps; no fresh AC replay",
            "embedding": "120 sampled profile/site/variant rows (6 dates x 2 groups x 2 sites x 5 variants), fresh snapshot AC bounds; diagnostic only",
        },
        "caveat": "No multi-feeder, phase-allocation, inverter-Q, kVA curve, or field experiment is claimed by this audit.",
        "counts": {"gate_rows": int(len(gate)), "policy_rows": int(len(policy)), "replay_sample_rows": int(len(replay)), "prefix_rows": int(len(pref)), "numerical_rows": int(len(numerical)), "device_rows": int(len(device)), "embedding_rows": int(len(embedding))},
    }
    (args.out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    readme = f"""# AC coverage and scope audit (round 1)\n\nThis directory reports reproducible diagnostics for the outstanding AC-coupling, baseline-gate, device-cap, synthetic-embedding, and numerical-tolerance questions. It does not change the frozen strict-v4 primary results.\n\n- `unconditional_gate_summary.csv` uses all 2,190 date-group units per placement, including zero-power gate failures.\n- `scalar_vs_replay_sample.csv` is a stratified 200-unit sample (10 dates x 10 groups x 2 placements). `replay_endpoint_checked_kw` is at least the scalar endpoint when that endpoint passes all 48 nonlinear snapshots; a failing endpoint receives a lower-power search. It is a sample diagnostic, not a new full-population endpoint.\n- `prefix_monotonicity_sample.csv` checks every interval, both signs, and the complete 0--300 kW / 20 kW candidate grid for that same sample. A later feasible point after a failed candidate is counted explicitly.\n- `numerical_sensitivity_sample.csv` varies the declared voltage/loading tolerance, command readback floor, and candidate-grid step on a 40-unit sample.\n- `device_power_cap_summary.csv` clips frozen scalar charge/export bounds by a symmetric power rating; it is not an AC inverter model.\n- `embedding_sensitivity_summary.csv` varies load gain, PV rating, and PV location on six dates and two groups per site using fresh AC snapshot bounds.\n\nThe evidence supports bounded model-based screening claims only. It does not establish cross-feeder transferability or a physical inverter capability guarantee.\n"""
    (args.out / "README.md").write_text(readme)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
