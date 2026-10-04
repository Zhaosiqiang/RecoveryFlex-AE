#!/usr/bin/env python3
"""Held-out factorial audit for the Applied Energy manuscript.

The corrected v1 result is deliberately stress-tested before submission.  The
audit keeps the offer rule frozen and varies the profile group, BESS placement,
and fixed PV embedding.  It reports the AC success frontier alongside the
copper-plate SOC limit, so the paper can separate a network haircut from a
state-of-charge haircut instead of attributing an algebraic SOC result to the
feeder model.
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

from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.profile_bank import load_bank
from run_corrected_experiment import (
    BANK_PATH, FEEDER_PATH, BATTERY_SITE, PV_RATED_KW, SERVICE_STARTS,
    SOC_INITIAL, SOC_RESERVE, ENERGY_KWH, ETA_DISCHARGE, DT_H,
    _embed, _event_ac, _select_days, P_GRID, VOLTAGE_LIMITS, LINE_LIMIT,
    RECOVERY_RATIO, ETA_CHARGE, RECOVERY_INTERVALS, SERVICE_INTERVALS,
)

OUT = ROOT / "results" / "factorial_v2"
GROUPS = tuple(range(10))
PLACEMENTS = ("611.3", "634.1", "692.3")
PV_LEVELS = (150.0, 300.0, 400.0, 500.0)


def copper_plate_limit() -> float:
    """Single-event SOC-only upper bound on the frozen command grid."""
    feasible = []
    for p in P_GRID:
        after = SOC_INITIAL - float(p) * DT_H * 4 / (ETA_DISCHARGE * ENERGY_KWH)
        if after >= SOC_RESERVE - 1e-12:
            feasible.append(float(p))
    return max(feasible) if feasible else 0.0


def copper_plate_sequence() -> list[dict]:
    """Energy-only sequence frontier for the same contract parameters."""
    rows = []
    for events in range(1, 7):
        feasible = []
        for p in P_GRID:
            soc = SOC_INITIAL
            ok = True
            for _ in range(events):
                soc = soc - float(p) * DT_H * SERVICE_INTERVALS / (ETA_DISCHARGE * ENERGY_KWH)
                if soc < SOC_RESERVE - 1e-12:
                    ok = False
                    break
                soc = min(1.0, soc + RECOVERY_RATIO * float(p) * DT_H * RECOVERY_INTERVALS * ETA_CHARGE / ENERGY_KWH)
            if ok:
                feasible.append(float(p))
        rows.append({"events": events, "capacity_kw": max(feasible) if feasible else 0.0})
    return rows


def _profiles(bank):
    return {g: _embed(bank, g) for g in GROUPS}


def _audit_event(feeder, load, pv, day, start, p, site):
    feeder.reset()
    return _event_ac(feeder, load, pv, int(day), int(start), float(p), battery_site=site)


def _success(frontier_feeder, profiles, days, dates, p, site):
    rows = []
    for day in days:
        for group, (load, pv) in profiles.items():
            for event_id, start in enumerate(SERVICE_STARTS, 1):
                ac_ok, vmin, vmax, loading, error, service, recovery = _audit_event(
                    frontier_feeder, load, pv, int(day), int(start), float(p), site
                )
                rows.append({
                    "date": str(dates[int(day)]), "day_index": int(day), "group": int(group),
                    "event_id": event_id, "site": site, "command_kw": float(p),
                    "ac_ok": int(ac_ok), "vmin": vmin, "vmax": vmax,
                    "max_loading": loading, "service_realized_kw": service,
                    "recovery_realized_kw": recovery, "error": error,
                })
    return rows


def run(max_train_days: int = 0, max_test_days: int = 0, out_dir: Path = OUT):
    bank = load_bank(BANK_PATH)
    profiles = _profiles(bank)
    train_days = _select_days(bank, "train", max_train_days)
    test_days = _select_days(bank, "test", max_test_days)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Offer selection uses all ten fixed groups and all training dates.  The
    # command grid and 95% event threshold are inherited from the main
    # protocol and are not tuned after looking at test rows.
    feeder = ACSnapshotFeeder(FEEDER_PATH, battery_sites=(BATTERY_SITE,),
                              pv_sites={"675.1": PV_RATED_KW},
                              voltage_limits=VOLTAGE_LIMITS,
                              line_loading_limit=LINE_LIMIT)
    offer_rows = []
    for p in P_GRID:
        rows = _success(feeder, profiles, train_days, bank.dates, float(p), BATTERY_SITE)
        frac = float(np.mean([r["ac_ok"] for r in rows])) if rows else 0.0
        offer_rows.append({"command_kw": float(p), "train_ac_success": frac,
                           "n_events": len(rows)})
    offer_df = pd.DataFrame(offer_rows)
    admissible = offer_df.loc[offer_df.train_ac_success >= 0.95, "command_kw"]
    train_offer = float(admissible.max()) if len(admissible) else 0.0

    # Placement comparison at the frozen offer and at the next grid point
    # provides a predeclared network haircut check without re-selecting the
    # offer for every site.
    placement_rows = []
    for site in PLACEMENTS:
        f = ACSnapshotFeeder(FEEDER_PATH, battery_sites=(site,),
                             pv_sites={"675.1": PV_RATED_KW},
                             voltage_limits=VOLTAGE_LIMITS,
                             line_loading_limit=LINE_LIMIT)
        for p in (train_offer, train_offer + 10.0):
            placement_rows.extend(_success(f, profiles, test_days, bank.dates, p, site))

    # PV sensitivity is evaluated at the frozen offer and at zero service;
    # the latter detects a baseline over-voltage before any battery result is
    # interpreted.
    pv_rows = []
    for pv_rating in PV_LEVELS:
        f = ACSnapshotFeeder(FEEDER_PATH, battery_sites=(BATTERY_SITE,),
                             pv_sites={"675.1": pv_rating},
                             voltage_limits=VOLTAGE_LIMITS,
                             line_loading_limit=LINE_LIMIT)
        for p in (0.0, train_offer):
            for day in test_days:
                for group, (load, pv) in profiles.items():
                    for event_id, start in enumerate(SERVICE_STARTS, 1):
                        a = _audit_event(f, load, pv, int(day), int(start), p, BATTERY_SITE)
                        pv_rows.append({"pv_rated_kw": pv_rating, "command_kw": p,
                                        "date": str(day), "day_index": int(day),
                                        "group": int(group), "event_id": event_id,
                                        "ac_ok": int(a[0]), "vmin": a[1], "vmax": a[2],
                                        "max_loading": a[3], "error": a[4]})

    offer_df.to_csv(out_dir / "all_group_offer_selection.csv", index=False)
    placement_df = pd.DataFrame(placement_rows)
    placement_df.to_csv(out_dir / "placement_frontier_rows.csv", index=False)
    pv_df = pd.DataFrame(pv_rows)
    pv_df.to_csv(out_dir / "pv_sensitivity_rows.csv", index=False)
    summary = {
        "status": "factorial_v2",
        "train_dates": int(len(train_days)), "test_dates": int(len(test_days)),
        "n_groups": len(GROUPS), "placements": list(PLACEMENTS),
        "pv_levels_kw": list(PV_LEVELS), "train_offer_kw_all_groups": train_offer,
        "copper_plate_soc_limit_kw": copper_plate_limit(),
        "copper_plate_sequence": copper_plate_sequence(),
        "pv_summary": (pv_df.groupby(["pv_rated_kw", "command_kw"], as_index=False)
                        .ac_ok.mean().rename(columns={"ac_ok": "test_ac_success"})
                        .to_dict(orient="records")),
        "placement_summary": (placement_df.groupby(["site", "command_kw"], as_index=False)
                              .ac_ok.mean().rename(columns={"ac_ok": "test_ac_success"})
                              .to_dict(orient="records")),
    }
    (out_dir / "factorial_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-train-days", type=int, default=0)
    ap.add_argument("--max-test-days", type=int, default=0)
    ap.add_argument("--out-dir", type=Path, default=OUT)
    args = ap.parse_args()
    print(json.dumps(run(args.max_train_days, args.max_test_days, args.out_dir), indent=2))
