#!/usr/bin/env python3
"""AC-replay a common empirical screening threshold.

The earlier descriptive threshold used the frontier schedules that define the
sample. This script adds a fixed-power LP schedule at each 95% network
threshold and replays that common schedule through the nonlinear feeder, so
coverage and AC replay are measured at the same declared power.
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
from recoveryflex.profile_bank import load_bank
import run_corrected_experiment as exp
from run_network_recovery_v2 import (
    _embedded_external, _replay, WINDOWS, FIXED_RECOVERY_WINDOWS,
    REARM_RATIO, BATTERY_ENERGY_KWH, AC_CONSTRAINT_TOLERANCE,
)

DEFAULT_PRIMARY = ROOT / "results/network_recovery_external_2012_2013_strict_v4"
DEFAULT_OUT = ROOT / "results/common_offer_replay_strict_v5"
DEFAULT_SOURCE = ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz"


def run(primary: Path = DEFAULT_PRIMARY, out_dir: Path = DEFAULT_OUT,
        source: Path = DEFAULT_SOURCE, site: str = "611.3") -> pd.DataFrame:
    safe = pd.read_csv(primary.parent / "safe_offer_metrics_strict_v4" / "safe_offer_metrics.csv")
    offer_row = safe[(safe.site.astype(str) == str(site)) &
                     (safe.method == "network_lp") &
                     (safe.target_empirical_coverage == 0.95)]
    if len(offer_row) != 1:
        raise ValueError(f"expected one 95% network threshold for site {site}")
    offer = float(offer_row.iloc[0].offer_kw)
    audit = pd.read_csv(primary / "baseline_zero_audit.csv")
    audit.site = audit.site.astype(str)
    audit = audit[(audit.site == str(site)) & (audit.baseline_zero_feasible.astype(int) == 1)].copy()
    bounds = pd.read_csv(primary / "ac_bounds.csv")
    bounds.site = bounds.site.astype(str)
    bank = load_bank(exp.BANK_PATH)
    load, pv, dates = _embedded_external(bank, source)
    feeder = ACSnapshotFeeder(
        exp.FEEDER_PATH, battery_sites=(str(site),), pv_sites={"675.1": exp.PV_RATED_KW},
        voltage_limits=exp.VOLTAGE_LIMITS, line_loading_limit=exp.LINE_LIMIT,
        constraint_tolerance=AC_CONSTRAINT_TOLERANCE,
    )
    rows = []
    common_base = dict(
        service_windows=WINDOWS, recovery_windows=FIXED_RECOVERY_WINDOWS,
        energy_kwh=BATTERY_ENERGY_KWH, initial_soc=exp.SOC_INITIAL,
        terminal_soc_target=exp.SOC_INITIAL, soc_min=exp.SOC_RESERVE, soc_max=1.0,
        eta_charge=exp.ETA_CHARGE, eta_discharge=exp.ETA_DISCHARGE, dt_h=exp.DT_H,
        terminal_mode="exact", mode="network_lp", service_power_kw=offer,
    )
    for r in audit.itertuples(index=False):
        day, group = int(r.day_index), int(r.group)
        b = bounds[(bounds.site == str(site)) & (bounds.day_index == day) &
                   (bounds.group == group)].sort_values("interval")
        if len(b) != 48:
            raise ValueError(f"missing 48 bound rows for {dates[day]}/{group}/{site}")
        ld, pv_d = load[day, :48, group], pv[day, :48, group]
        result = plan_service(
            charge_limit_kw=b.charge_limit_kw.to_numpy(float),
            export_limit_kw=b.export_limit_kw.to_numpy(float),
            load_kw=ld, **common_base,
        )
        replay_ok, audits = _replay(feeder, ld, pv_d, str(site), result)
        rows.append({
            "date": str(dates[day]), "day_index": day, "group": group, "site": str(site),
            "threshold_kw": offer, "planner_feasible": int(result.feasible),
            "replay_feasible": int(replay_ok), "terminal_soc": float(result.terminal_soc),
            "max_vmax": float(max((a.vmax for a in audits if np.isfinite(a.vmax)), default=np.nan)),
            "max_loading": float(max((a.max_line_loading for a in audits if np.isfinite(a.max_line_loading)), default=np.nan)),
            "message": result.message,
        })
    out = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_dir / f"rows_{str(site).replace('.', '_')}.csv", index=False)
    summary = {
        "status": "common_offer_replay_strict_v5",
        "site": str(site), "threshold_kw": offer,
        "target_empirical_coverage": 0.95, "n_units": int(len(out)),
        "planner_feasible_rate": float(out.planner_feasible.mean()),
        "replay_feasible_rate": float(out.replay_feasible.mean()),
        "source": str(source), "protocol": "fixed network-LP service_power_kw with nonlinear OpenDSS replay",
    }
    (out_dir / f"summary_{str(site).replace('.', '_')}.json").write_text(json.dumps(summary, indent=2))
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default="611.3")
    ap.add_argument("--primary", type=Path, default=DEFAULT_PRIMARY)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    args = ap.parse_args()
    result = run(args.primary, args.out_dir, args.source, args.site)
    print(result.groupby("site")["replay_feasible"].mean().to_string())
