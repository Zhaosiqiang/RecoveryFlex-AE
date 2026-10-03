#!/usr/bin/env python3
"""Run the corrected, auditable RecoveryFlex experiment.

This script is deliberately independent of the invalid V0 pipeline.  It uses
the interval-resolved Ausgrid bank, a physically measured OpenDSS constant-PQ
battery, chronological train/calibration/test splits, and an explicit SOC
state.  The full-rearm control resets SOC before every event; the reserve-
limited sequence carries SOC across events.  Thus any contraction in the
sequence result has an identifiable energy-state cause rather than a hidden
scenario change or a hand-coded telemetry uplift.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.profile_bank import load_bank, ProfileBank


BANK_PATH = ROOT / "data" / "processed" / "ausgrid_profile_bank_v2.npz"
FEEDER_PATH = ROOT / "data" / "raw" / "IEEE13Nodeckt.dss"
OUT_DIR = ROOT / "results" / "corrected_v1"

# All constants are fixed before looking at outcomes.  The load/PV embedding is
# a scale bridge from measured household kW to the public IEEE-13 snapshot.
GROUP = 0
BATTERY_SITE = "611.3"
PV_RATED_KW = 300.0
LOAD_OFFSET = 0.40
LOAD_GAIN = 0.30
PV_OFFSET = 0.10
PV_GAIN = 0.60
SERVICE_STARTS = (8, 32)
SERVICE_INTERVALS = 4
RECOVERY_INTERVALS = 8
DT_H = 0.5
ENERGY_KWH = 500.0
SOC_INITIAL = 0.80
SOC_RESERVE = 0.20
ETA_DISCHARGE = 0.95
ETA_CHARGE = 0.95
RECOVERY_RATIO = 0.30
P_GRID = np.arange(0.0, 301.0, 10.0)
VOLTAGE_LIMITS = (0.95, 1.05)
LINE_LIMIT = 1.0


@dataclass(frozen=True)
class EventResult:
    ac_ok: bool
    energy_ok: bool
    ok: bool
    soc_start: float
    soc_after_service: float
    soc_after_recovery: float
    vmin: float
    vmax: float
    max_loading: float
    error: str = ""


def _embed(bank: ProfileBank) -> tuple[np.ndarray, np.ndarray]:
    """Map measured interval profiles to fixed feeder exogenous factors."""
    load = np.clip(
        LOAD_OFFSET + LOAD_GAIN * bank.load_kw[:, :, GROUP] / bank.train_load_scale_kw[GROUP],
        0.35,
        0.85,
    )
    pv = np.clip(
        PV_OFFSET + PV_GAIN * bank.pv_kw[:, :, GROUP] / bank.train_pv_scale_kw[GROUP],
        0.0,
        1.0,
    )
    return load, pv


def _event_ac(
    feeder: ACSnapshotFeeder,
    load: np.ndarray,
    pv: np.ndarray,
    day: int,
    start: int,
    p_kw: float,
    recovery_ratio: float = RECOVERY_RATIO,
) -> tuple[bool, float, float, float, str]:
    """Audit every service/recovery snapshot and return extrema."""
    vmins: list[float] = []
    vmaxs: list[float] = []
    loadings: list[float] = []
    errors: list[str] = []
    for t in range(start, start + SERVICE_INTERVALS):
        a = feeder.solve(float(load[day, t]), float(pv[day, t]), {BATTERY_SITE: float(p_kw)})
        if not a.feasible:
            errors.append(a.error or "service AC infeasible")
        vmins.append(a.vmin)
        vmaxs.append(a.vmax)
        loadings.append(a.max_line_loading)
    for t in range(start + SERVICE_INTERVALS, start + SERVICE_INTERVALS + RECOVERY_INTERVALS):
        a = feeder.solve(float(load[day, t]), float(pv[day, t]), {BATTERY_SITE: float(-recovery_ratio * p_kw)})
        if not a.feasible:
            errors.append(a.error or "recovery AC infeasible")
        vmins.append(a.vmin)
        vmaxs.append(a.vmax)
        loadings.append(a.max_line_loading)
    fvmin = [x for x in vmins if np.isfinite(x)]
    fvmax = [x for x in vmaxs if np.isfinite(x)]
    fload = [x for x in loadings if np.isfinite(x)]
    return (
        not errors,
        float(np.min(fvmin)) if fvmin else float("nan"),
        float(np.max(fvmax)) if fvmax else float("nan"),
        float(np.max(fload)) if fload else float("nan"),
        "; ".join(errors[:2]),
    )


def evaluate_event(
    feeder: ACSnapshotFeeder,
    load: np.ndarray,
    pv: np.ndarray,
    day: int,
    start: int,
    p_kw: float,
    soc_start: float,
    recovery_ratio: float = RECOVERY_RATIO,
    require_rearm: bool = False,
) -> EventResult:
    # OpenDSS retains the last converged operating point and a failed
    # high-power solve can otherwise contaminate the next candidate.  Rebuild
    # the isolated snapshot before each event so train/cal/test outcomes are
    # independent of candidate-grid order.
    feeder.reset()
    ac_ok, vmin, vmax, max_loading, error = _event_ac(
        feeder, load, pv, day, start, p_kw, recovery_ratio=recovery_ratio
    )
    soc_after_service = float(soc_start - p_kw * DT_H * SERVICE_INTERVALS / (ETA_DISCHARGE * ENERGY_KWH))
    energy_ok = bool(soc_after_service >= SOC_RESERVE - 1e-12 and soc_after_service <= 1.0 + 1e-12)
    soc_after_recovery = float(min(1.0, soc_after_service + recovery_ratio * p_kw * DT_H * RECOVERY_INTERVALS * ETA_CHARGE / ENERGY_KWH))
    if require_rearm:
        energy_ok = bool(energy_ok and soc_after_recovery >= SOC_INITIAL - 1e-8)
    return EventResult(bool(ac_ok), energy_ok, bool(ac_ok and energy_ok), float(soc_start), soc_after_service, soc_after_recovery, vmin, vmax, max_loading, error)


def _rearm_ratio(p_kw: float) -> float:
    """Charging-to-service power ratio that restores the pre-event SOC."""
    del p_kw  # the ratio is independent of the requested service magnitude
    return float(SERVICE_INTERVALS / (RECOVERY_INTERVALS * ETA_DISCHARGE * ETA_CHARGE))


def _select_days(bank: ProfileBank, split: str, limit: int) -> np.ndarray:
    idx = np.where(bank.split == split)[0]
    if limit <= 0 or len(idx) <= limit:
        return idx
    # Evenly spaced calendar coverage, chosen before outcomes are computed.
    return idx[np.linspace(0, len(idx) - 1, limit).round().astype(int)]


def _event_success_fraction(feeder, load, pv, days: Iterable[int], p_kw: float, starts=SERVICE_STARTS) -> float:
    vals = []
    for day in days:
        for start in starts:
            vals.append(evaluate_event(feeder, load, pv, int(day), int(start), float(p_kw), SOC_INITIAL).ok)
    return float(np.mean(vals)) if vals else 0.0


def _largest_grid_offer(feeder, load, pv, days: np.ndarray, threshold: float = 0.95) -> tuple[float, dict[float, float]]:
    fractions: dict[float, float] = {}
    for p in P_GRID:
        # A failed high-power Newton solve must not influence the next
        # candidate. Recompile the isolated context for each candidate.
        feeder.reset()
        fractions[float(p)] = _event_success_fraction(feeder, load, pv, days, float(p))
    feasible = [p for p, f in fractions.items() if f >= threshold]
    return (max(feasible) if feasible else 0.0), fractions


def run(max_train_days: int = 0, max_cal_days: int = 0, max_test_days: int = 0, out_dir: Path = OUT_DIR) -> dict:
    bank = load_bank(BANK_PATH)
    load, pv = _embed(bank)
    feeder = ACSnapshotFeeder(
        FEEDER_PATH,
        battery_sites=(BATTERY_SITE,),
        pv_sites={"675.1": PV_RATED_KW},
        voltage_limits=VOLTAGE_LIMITS,
        line_loading_limit=LINE_LIMIT,
    )
    train_days = _select_days(bank, "train", max_train_days)
    cal_days = _select_days(bank, "cal", max_cal_days)
    test_days = _select_days(bank, "test", max_test_days)

    p_train_max, train_grid = _largest_grid_offer(feeder, load, pv, train_days)
    # Calibration can reduce the training offer by a predeclared margin.  The
    # largest admissible factor is selected using calibration days only.
    cal_fractions: dict[str, float] = {}
    chosen_factor = 0.0
    for factor in (0.80, 0.90, 1.00):
        p = factor * p_train_max
        feeder.reset()
        frac = _event_success_fraction(feeder, load, pv, cal_days, p)
        cal_fractions[f"{factor:.2f}"] = frac
        if frac >= 0.95:
            chosen_factor = factor
    final_offer = float(chosen_factor * p_train_max)

    rows: list[dict] = []
    for split, days in (("train", train_days), ("cal", cal_days), ("test", test_days)):
        p = final_offer if split != "train" else p_train_max
        for day in days:
            for event_id, start in enumerate(SERVICE_STARTS, 1):
                r = evaluate_event(feeder, load, pv, int(day), int(start), p, SOC_INITIAL)
                rows.append({"phase": "single", "split": split, "date": str(bank.dates[day]), "day_index": int(day), "event_id": event_id, "offer_kw": p, "ok": int(r.ok), "ac_ok": int(r.ac_ok), "energy_ok": int(r.energy_ok), "soc_start": r.soc_start, "soc_after_service": r.soc_after_service, "soc_after_recovery": r.soc_after_recovery, "vmin": r.vmin, "vmax": r.vmax, "max_line_loading": r.max_loading, "error": r.error})

    # Full-rearm negative control: duplicate one measured event exactly and
    # reset SOC before each repetition.  This must yield C_M=1 whenever the
    # single event is feasible; there is no state or scenario change here.
    control_day = int(test_days[0])
    control_start = int(SERVICE_STARTS[0])
    rearm_ratio = _rearm_ratio(final_offer)
    control_single = evaluate_event(
        feeder, load, pv, control_day, control_start, final_offer, SOC_INITIAL,
        recovery_ratio=rearm_ratio, require_rearm=True,
    )
    rearm_events = [control_single, evaluate_event(
        feeder, load, pv, control_day, control_start, final_offer, SOC_INITIAL,
        recovery_ratio=rearm_ratio, require_rearm=True,
    )]
    rearm_c2 = float(np.mean([r.ok for r in rearm_events]) / max(int(control_single.ok), 1))
    for eid, r in enumerate(rearm_events, 1):
        rows.append({"phase": "full_rearm_control", "split": "test", "date": str(bank.dates[control_day]), "day_index": control_day, "event_id": eid, "offer_kw": final_offer, "ok": int(r.ok), "ac_ok": int(r.ac_ok), "energy_ok": int(r.energy_ok), "soc_start": r.soc_start, "soc_after_service": r.soc_after_service, "soc_after_recovery": r.soc_after_recovery, "vmin": r.vmin, "vmax": r.vmax, "max_line_loading": r.max_loading, "error": r.error})

    # Reserve-limited non-reset sequence: repeat exactly the same physical
    # event while carrying SOC.  The only changing state is the documented
    # reserve/energy state, so C2 is identifiable.
    soc = SOC_INITIAL
    sequence: list[EventResult] = []
    for eid in range(1, 3):
        r = evaluate_event(feeder, load, pv, control_day, control_start, final_offer, soc)
        sequence.append(r)
        rows.append({"phase": "nonreset_sequence", "split": "test", "date": str(bank.dates[control_day]), "day_index": control_day, "event_id": eid, "offer_kw": final_offer, "ok": int(r.ok), "ac_ok": int(r.ac_ok), "energy_ok": int(r.energy_ok), "soc_start": r.soc_start, "soc_after_service": r.soc_after_service, "soc_after_recovery": r.soc_after_recovery, "vmin": r.vmin, "vmax": r.vmax, "max_line_loading": r.max_loading, "error": r.error})
        if not r.ok:
            break
        soc = r.soc_after_recovery
    nonreset_c2 = float(np.mean([r.ok for r in sequence]) / max(int(sequence[0].ok), 1))

    # Capacity by sequence length on repeated copies of one held-out event.
    # This isolates the persistent energy state from profile transitions and
    # gives the main sequence-level figure a full-rearm negative control.
    capacity_rows: list[dict] = []
    for sequence_day in test_days:
        sequence_day = int(sequence_day)
        for mode in ("full_rearm", "reserve_limited"):
            # The physical event is identical at every repeated call.  Cache
            # its AC audit once per (day, mode, P); only the SOC recursion
            # changes with the sequence length.  This keeps the full audit
            # reproducible without millions of duplicate OpenDSS solves.
            ac_cache = {}
            for p in P_GRID:
                ratio = _rearm_ratio(float(p)) if mode == "full_rearm" else RECOVERY_RATIO
                feeder.reset()
                ac_cache[float(p)] = _event_ac(
                    feeder, load, pv, sequence_day, control_start, float(p),
                    recovery_ratio=ratio,
                )[0]
            for events in range(1, 7):
                feasible_grid: list[float] = []
                for p in P_GRID:
                    soc = SOC_INITIAL
                    ok = bool(ac_cache[float(p)])
                    for _ in range(events):
                        if not ok:
                            break
                        soc_after_service = soc - float(p) * DT_H * SERVICE_INTERVALS / (ETA_DISCHARGE * ENERGY_KWH)
                        if soc_after_service < SOC_RESERVE - 1e-12 or soc_after_service > 1.0 + 1e-12:
                            ok = False
                            break
                        ratio = _rearm_ratio(float(p)) if mode == "full_rearm" else RECOVERY_RATIO
                        soc = min(1.0, soc_after_service + ratio * float(p) * DT_H * RECOVERY_INTERVALS * ETA_CHARGE / ENERGY_KWH)
                        if mode == "full_rearm" and soc < SOC_INITIAL - 1e-8:
                            ok = False
                            break
                    if ok:
                        feasible_grid.append(float(p))
                capacity_rows.append({
                    "mode": mode, "events": events,
                    "capacity_kw": max(feasible_grid) if feasible_grid else 0.0,
                    "date": str(bank.dates[sequence_day]), "day_index": sequence_day,
                })

    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out_dir / "corrected_experiment_rows.csv", index=False)
    summary = {
        "status": "corrected_v1",
        "bank": str(BANK_PATH),
        "feeder": str(FEEDER_PATH),
        "selected_dates": {"train": [str(bank.dates[i]) for i in train_days], "cal": [str(bank.dates[i]) for i in cal_days], "test": [str(bank.dates[i]) for i in test_days]},
        "train_grid_success": {str(k): float(v) for k, v in train_grid.items()},
        "calibration_success": cal_fractions,
        "p_train_max_kw": float(p_train_max),
        "calibration_factor": float(chosen_factor),
        "final_offer_kw": final_offer,
        "full_rearm_control_C2": rearm_c2,
        "nonreset_sequence_C2": nonreset_c2,
        "nonreset_sequence_events": len(sequence),
        "full_rearm_recovery_ratio": rearm_ratio,
        "sequence_capacity_rows": len(capacity_rows),
        "constants": {"group": GROUP, "battery_site": BATTERY_SITE, "pv_site": "675.1", "pv_rated_kw": PV_RATED_KW, "load_offset": LOAD_OFFSET, "load_gain": LOAD_GAIN, "pv_offset": PV_OFFSET, "pv_gain": PV_GAIN, "service_starts": list(SERVICE_STARTS), "service_intervals": SERVICE_INTERVALS, "recovery_intervals": RECOVERY_INTERVALS, "dt_h": DT_H, "energy_kwh": ENERGY_KWH, "soc_initial": SOC_INITIAL, "soc_reserve": SOC_RESERVE, "eta_discharge": ETA_DISCHARGE, "eta_charge": ETA_CHARGE, "recovery_ratio": RECOVERY_RATIO, "voltage_limits_pu": VOLTAGE_LIMITS, "line_loading_limit": LINE_LIMIT, "selection_threshold": 0.95},
    }
    (out_dir / "corrected_experiment_summary.json").write_text(json.dumps(summary, indent=2))
    pd.DataFrame(capacity_rows).to_csv(out_dir / "sequence_capacity.csv", index=False)
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    # Zero means all dates in the corresponding predeclared split.  Small
    # smoke runs can pass explicit positive limits without changing the method.
    ap.add_argument("--max-train-days", type=int, default=0)
    ap.add_argument("--max-cal-days", type=int, default=0)
    ap.add_argument("--max-test-days", type=int, default=0)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    print(json.dumps(run(args.max_train_days, args.max_cal_days, args.max_test_days, args.out_dir), indent=2))
