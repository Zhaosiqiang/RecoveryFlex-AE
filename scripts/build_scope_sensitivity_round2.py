#!/usr/bin/env python3
"""Run a small predeclared embedding audit for the review scope.

The primary paper intentionally uses a frozen load/PV embedding.  This
diagnostic adds the missing ``night_pv_zero`` check requested by the review:
the normalized PV surrogate is set to zero during 00:00--06:00 (intervals
0--11), removing the ``PV_OFFSET`` contribution in the nominal night block.
It also retains an all-day ``pv_zero`` negative control.  The audit uses fresh
IEEE-13 snapshot bounds and the same scalar dispatch contract, but it is a
small sample and is not substituted for the primary result.
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
sys.path.insert(0, str(ROOT / "scripts"))

from recoveryflex.dispatch import plan_service
from recoveryflex.ac_snapshot import ACSnapshotFeeder
import run_corrected_experiment as exp
import run_network_recovery_v2 as protocol
from recoveryflex.profile_bank import load_bank


def _embed(source: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dev = load_bank(exp.BANK_PATH)
    x = np.load(source, allow_pickle=False)
    load = np.transpose(x["load_kw"], (0, 2, 1))
    pv = np.transpose(x["pv_kw"], (0, 2, 1))
    load = np.clip(exp.LOAD_OFFSET + exp.LOAD_GAIN * load / dev.train_load_scale_kw[None, None, :], 0.35, 0.85)
    pv = np.clip(exp.PV_OFFSET + exp.PV_GAIN * pv / dev.train_pv_scale_kw[None, None, :], 0.0, 1.0)
    return load, pv, x["dates"].astype(str)


def _dispatch(charge: np.ndarray, export: np.ndarray, load: np.ndarray):
    return plan_service(
        charge_limit_kw=charge,
        export_limit_kw=export,
        load_kw=load,
        service_windows=protocol.WINDOWS,
        recovery_windows=protocol.FIXED_RECOVERY_WINDOWS,
        energy_kwh=protocol.BATTERY_ENERGY_KWH,
        initial_soc=exp.SOC_INITIAL,
        terminal_soc_target=exp.SOC_INITIAL,
        soc_min=exp.SOC_RESERVE,
        soc_max=1.0,
        eta_charge=exp.ETA_CHARGE,
        eta_discharge=exp.ETA_DISCHARGE,
        dt_h=exp.DT_H,
        terminal_mode="exact",
        mode="network_lp",
    )


def run(*, source: Path, out_dir: Path, days: tuple[int, ...], groups: tuple[int, ...]) -> dict[str, object]:
    load, pv, dates = _embed(source)
    sites = ("611.3", "634.1")
    variants = ("frozen", "night_pv_zero", "pv_zero")
    rows: list[dict[str, object]] = []
    for variant in variants:
        for site in sites:
            feeder = ACSnapshotFeeder(
                exp.FEEDER_PATH,
                battery_sites=(site,),
                pv_sites={"675.1": exp.PV_RATED_KW},
                voltage_limits=exp.VOLTAGE_LIMITS,
                line_loading_limit=exp.LINE_LIMIT,
                constraint_tolerance=1e-6,
            )
            for day in days:
                for group in groups:
                    ld = load[day, :48, group]
                    pv_day = pv[day, :48, group].copy()
                    if variant == "night_pv_zero":
                        pv_day[:12] = 0.0
                    elif variant == "pv_zero":
                        pv_day[:] = 0.0
                    charge, export, reasons = protocol._bounds(feeder, ld, pv_day, site)
                    result = _dispatch(np.asarray(charge), np.asarray(export), ld)
                    rows.append({
                        "variant": variant,
                        "site": site,
                        "day_index": int(day),
                        "date": str(dates[day]),
                        "group": int(group),
                        "night_intervals": "0:00--06:00" if variant == "night_pv_zero" else "unchanged",
                        "pv_mean_nominal": float(np.mean(pv[day, :12, group])),
                        "pv_mean_used": float(np.mean(pv_day[:12])),
                        "pv_total_nominal_pu_h": float(np.sum(pv[day, :12, group]) * exp.DT_H),
                        "pv_total_used_pu_h": float(np.sum(pv_day[:12]) * exp.DT_H),
                        "baseline_reason_count": int(len(reasons)),
                        "planner_feasible": int(result.feasible),
                        "service_endpoint_kw": float(result.service_kw),
                    })
    frame = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out_dir / "night_pv_zero_rows.csv", index=False)
    summary = frame.groupby("variant", as_index=False).agg(
        n=("service_endpoint_kw", "size"),
        mean_endpoint_kw=("service_endpoint_kw", "mean"),
        p05_endpoint_kw=("service_endpoint_kw", lambda x: float(x.quantile(0.05))),
        p95_endpoint_kw=("service_endpoint_kw", lambda x: float(x.quantile(0.95))),
        baseline_failures=("baseline_reason_count", lambda x: int((x > 0).sum())),
        planner_failures=("planner_feasible", lambda x: int((x == 0).sum())),
    )
    summary.to_csv(out_dir / "night_pv_zero_summary.csv", index=False)
    metadata = {
        "status": "scope_sensitivity_round2",
        "source": str(source.relative_to(ROOT)),
        "sites": list(sites),
        "variants": list(variants),
        "night_definition": "normalized PV surrogate set to zero for intervals 0--11 (00:00--06:00)",
        "contract": "same 48-interval two-call scalar AC-bound LP as primary experiment",
        "sample_days": [int(x) for x in days],
        "sample_groups": [int(x) for x in groups],
        "seed": 20261003,
        "claim_boundary": "sample diagnostic only; no phase allocation or cross-feeder inference",
        "rows": int(len(frame)),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (out_dir / "README.md").write_text(
        "# Scope sensitivity round 2\n\n"
        "This small fresh-AC snapshot audit tests the missing night-PV=0 embedding variant. "
        "It is not a replacement for the frozen primary results. The `night_pv_zero` variant "
        "sets the normalized PV surrogate to zero from 00:00 to 06:00; `pv_zero` is an all-day "
        "negative control. Customer-to-bus phase mapping remains uncalibrated and is not inferred.\n"
    )
    print(summary.to_string(index=False))
    return metadata


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "results/scope_sensitivity_round2")
    ap.add_argument("--days", type=str, default="0,102,218")
    ap.add_argument("--groups", type=str, default="0")
    args = ap.parse_args()
    days = tuple(int(x) for x in args.days.split(",") if x.strip())
    groups = tuple(int(x) for x in args.groups.split(",") if x.strip())
    print(json.dumps(run(source=args.source, out_dir=args.out_dir, days=days, groups=groups), indent=2))


if __name__ == "__main__":
    main()
