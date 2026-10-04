#!/usr/bin/env python3
"""Reproduce AC failure classes for failed policy replays.

The main experiment stores compact policy rows.  This companion audit
reconstructs each failed schedule from the frozen AC bounds and records every
OpenDSS failure reason, limiting component, and interval.  It is deliberately
read-only with respect to the result directory.
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
from recoveryflex.dispatch import plan_service
from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.profile_bank import load_bank
import run_network_recovery_v2 as protocol


def _failure_class(reason: str) -> str:
    s = str(reason).lower()
    if "voltage" in s:
        return "voltage"
    if "transformer" in s:
        return "transformer"
    if "line_loading" in s:
        return "line"
    if "battery_readback" in s or "unknown_battery" in s:
        return "command_readback"
    if "nonconverged" in s or "adapter_exception" in s:
        return "convergence"
    if "soc" in s:
        return "soc"
    return "other"


def run(results_dir: Path, source: Path, out: Path) -> dict:
    rows = pd.read_csv(results_dir / "policy_rows.csv")
    bounds = pd.read_csv(results_dir / "ac_bounds.csv")
    failed = rows[rows.replay_feasible == 0].copy()
    if failed.empty:
        pd.DataFrame(columns=["date", "group", "site", "method", "interval", "failure_class", "reason"]).to_csv(out, index=False)
        return {"n_failed_policy_rows": 0, "n_failure_records": 0}

    dev = load_bank(exp.BANK_PATH)
    raw = np.load(source, allow_pickle=False)
    load = np.transpose(raw["load_kw"], (0, 2, 1))
    pv = np.transpose(raw["pv_kw"], (0, 2, 1))
    load = np.clip(exp.LOAD_OFFSET + exp.LOAD_GAIN * load / dev.train_load_scale_kw[None, None, :], 0.35, 0.85)
    pv = np.clip(exp.PV_OFFSET + exp.PV_GAIN * pv / dev.train_pv_scale_kw[None, None, :], 0.0, 1.0)
    dates = raw["dates"].astype(str)
    date_to_day = {d: i for i, d in enumerate(dates)}
    records = []
    feeders: dict[str, ACSnapshotFeeder] = {}
    for (date, group, site), unit in failed.groupby(["date", "group", "site"], sort=False):
        day = date_to_day[str(date)]
        g = int(group)
        s = str(site)
        if s not in feeders:
            feeders[s] = ACSnapshotFeeder(
                exp.FEEDER_PATH,
                battery_sites=(s,),
                pv_sites={"675.1": exp.PV_RATED_KW},
                voltage_limits=exp.VOLTAGE_LIMITS,
                line_loading_limit=exp.LINE_LIMIT,
            )
        feeder = feeders[s]
        ld = load[day, :protocol.HORIZON_INTERVALS, g]
        pd_ = pv[day, :protocol.HORIZON_INTERVALS, g]
        b = bounds[(bounds.date.astype(str) == str(date)) & (bounds.group == g) & (bounds.site.astype(str) == s)].sort_values("interval")
        if len(b) != protocol.HORIZON_INTERVALS:
            raise ValueError(f"missing AC bounds for {(date, g, s)}: {len(b)} rows")
        common = dict(
            charge_limit_kw=b.charge_limit_kw.to_numpy(float),
            export_limit_kw=b.export_limit_kw.to_numpy(float),
            load_kw=ld,
            service_windows=protocol.WINDOWS,
            energy_kwh=protocol.BATTERY_ENERGY_KWH,
            initial_soc=exp.SOC_INITIAL,
            terminal_soc_target=exp.SOC_INITIAL,
            soc_min=exp.SOC_RESERVE,
            soc_max=1.0,
            eta_charge=exp.ETA_CHARGE,
            eta_discharge=exp.ETA_DISCHARGE,
            dt_h=exp.DT_H,
            terminal_mode="exact",
            recovery_windows=protocol.FIXED_RECOVERY_WINDOWS,
        )
        for method in unit.method.astype(str):
            if method == "network_lp":
                kw = {"mode": "network_lp"}
            elif method == "fixed_recovery":
                kw = {"mode": "fixed_recovery", "fixed_recovery_ratio": protocol.REARM_RATIO}
            elif method == "myopic_recovery":
                kw = {"mode": "myopic_recovery"}
            elif method == "energy_only":
                kw = {"mode": "energy_only"}
            else:
                continue
            result = plan_service(**common, **kw)
            for interval, (l, p, ch, dis) in enumerate(zip(ld, pd_, result.charge_kw, result.discharge_kw)):
                audit = feeder.solve(float(l), float(p), {s: float(dis - ch)})
                if audit.feasible:
                    continue
                reasons = audit.failure_reasons or (audit.error or "unknown_failure",)
                for reason in reasons:
                    records.append({
                        "date": str(date), "day_index": day, "group": g, "site": s,
                        "method": method, "interval": interval,
                        "failure_class": _failure_class(reason), "reason": str(reason),
                        "limiting_component": audit.limiting_component,
                        "vmin": audit.vmin, "vmax": audit.vmax,
                        "max_loading": audit.max_line_loading,
                        "max_transformer_loading": audit.max_transformer_loading,
                    })
    out.parent.mkdir(parents=True, exist_ok=True)
    result_df = pd.DataFrame(records)
    result_df.to_csv(out, index=False)
    summary = {
        "source_results": str(results_dir.resolve()),
        "source_profiles": str(source.resolve()),
        "n_failed_policy_rows": int(len(failed)),
        "n_failure_records": int(len(result_df)),
        "by_class": result_df.failure_class.value_counts().to_dict() if not result_df.empty else {},
        "by_method": result_df.groupby("method").size().to_dict() if not result_df.empty else {},
    }
    out.with_name(out.stem + "_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, required=True)
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(run(args.results_dir, args.source, args.out), indent=2))
