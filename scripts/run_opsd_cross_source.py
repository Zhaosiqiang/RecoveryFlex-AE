#!/usr/bin/env python3
"""Cross-source validation on the OPSD household profile bank.

This is an independent profile-source audit of the frozen v2 fair-window
contract.  OPSD's native 15-minute curves are reduced by adjacent-pair
averaging to the 48 half-hour intervals used by the main experiment.  The
OPSD training dates alone determine the two normalization scales; no result
from the Ausgrid path is used to select an operating point or policy.

The feeder, battery, voltage limits, AC snapshot adapter, and dispatch
contract are held fixed.  Outputs are diagnostic until the manuscript's
authors decide whether to include this validation in the journal package.
"""
from __future__ import annotations

import argparse
import hashlib
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
from run_network_recovery_v2 import (
    _bounds,
    _replay,
    WINDOWS,
    FIXED_RECOVERY_WINDOWS,
    REARM_RATIO,
    BATTERY_ENERGY_KWH,
    HORIZON_INTERVALS,
    AC_CONSTRAINT_TOLERANCE,
)

DEFAULT_SOURCE = ROOT / "data" / "processed" / "opsd_profile_bank_v2.npz"
DEFAULT_OUT = ROOT / "results" / "opsd_cross_source_strict_v5"
DEFAULT_SITES = ("611.3", "634.1")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_halfhour(source: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, object]]:
    """Return (load, pv, dates, split, metadata) in day x interval x group order."""
    x = np.load(source, allow_pickle=False)
    required = {"load_kw", "pv_kw", "dates", "split"}
    missing = sorted(required - set(x.files))
    if missing:
        raise ValueError(f"OPSD bank missing keys: {missing}")
    raw_load = np.asarray(x["load_kw"], dtype=float)
    raw_pv = np.asarray(x["pv_kw"], dtype=float)
    if raw_load.ndim != 2 or raw_pv.ndim != 2 or raw_load.shape != raw_pv.shape:
        raise ValueError(f"expected 2-D matching OPSD arrays, got {raw_load.shape}/{raw_pv.shape}")
    if raw_load.shape[1] != 96:
        raise ValueError(f"OPSD source must contain 96 quarter-hour intervals, got {raw_load.shape[1]}")
    # Adjacent 15-minute average powers produce the declared 30-minute mean.
    load = raw_load.reshape(raw_load.shape[0], 48, 2).mean(axis=2)[:, :, None]
    pv = raw_pv.reshape(raw_pv.shape[0], 48, 2).mean(axis=2)[:, :, None]
    dates = np.asarray(x["dates"]).astype(str)
    split = np.asarray(x["split"]).astype(str)
    if len(dates) != load.shape[0] or len(split) != load.shape[0]:
        raise ValueError("OPSD dates/split length does not match profile rows")
    if not np.isfinite(load).all() or not np.isfinite(pv).all():
        raise ValueError("OPSD profiles contain non-finite values")
    train = split == "train"
    if not train.any():
        raise ValueError("OPSD source contains no training dates")
    load_scale = np.maximum(load[train].max(axis=(0, 1)), 1e-12)
    pv_scale = np.maximum(pv[train].max(axis=(0, 1)), 1e-12)
    metadata = {
        "source": str(source),
        "source_sha256": sha256(source),
        "native_intervals_per_day": 96,
        "target_intervals_per_day": 48,
        "resampling": "arithmetic mean of adjacent 15-minute average-power values",
        "normalization": "OPSD train-only maximum per channel over all 48 half-hour intervals",
        "train_dates": [str(dates[np.where(train)[0][0]]), str(dates[np.where(train)[0][-1]])],
        "n_days": int(load.shape[0]),
        "n_test_days": int(np.sum(split == "test")),
        "train_load_scale_kw": float(load_scale[0]),
        "train_pv_scale_kw": float(pv_scale[0]),
    }
    # Store scales with the arrays for an explicit, auditable embedding path.
    metadata["load_scale_vector_kw"] = load_scale.tolist()
    metadata["pv_scale_vector_kw"] = pv_scale.tolist()
    return load, pv, dates, split, metadata


def embed(load_raw: np.ndarray, pv_raw: np.ndarray, train_load_scale: np.ndarray,
          train_pv_scale: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Apply the frozen stress embedding with OPSD-only normalization."""
    load = np.clip(
        exp.LOAD_OFFSET + exp.LOAD_GAIN * load_raw / train_load_scale[None, None, :],
        0.35,
        0.85,
    )
    pv = np.clip(
        exp.PV_OFFSET + exp.PV_GAIN * pv_raw / train_pv_scale[None, None, :],
        0.0,
        1.0,
    )
    return load, pv


def select_test_days(split: np.ndarray, max_days: int) -> np.ndarray:
    idx = np.where(split == "test")[0]
    if not len(idx):
        raise ValueError("OPSD source contains no test dates")
    if max_days <= 0 or max_days >= len(idx):
        return idx
    # Calendar-spread selection is fixed before any AC result is read.
    return idx[np.linspace(0, len(idx) - 1, int(max_days)).round().astype(int)]


def run(
    source: Path = DEFAULT_SOURCE,
    out_dir: Path = DEFAULT_OUT,
    max_days: int = 0,
    sites: tuple[str, ...] = DEFAULT_SITES,
) -> dict[str, object]:
    raw_load, raw_pv, dates, split, profile_meta = load_halfhour(source)
    train = split == "train"
    train_load_scale = np.maximum(raw_load[train].max(axis=(0, 1)), 1e-12)
    train_pv_scale = np.maximum(raw_pv[train].max(axis=(0, 1)), 1e-12)
    load, pv = embed(raw_load, raw_pv, train_load_scale, train_pv_scale)
    selected = select_test_days(split, max_days)
    if raw_load.shape[2] != 1:
        raise ValueError("This cross-source path expects one OPSD household profile group")

    rows: list[dict[str, object]] = []
    bound_rows: list[dict[str, object]] = []
    trace_rows: list[dict[str, object]] = []
    for site in sites:
        feeder = ACSnapshotFeeder(
            exp.FEEDER_PATH,
            battery_sites=(site,),
            pv_sites={"675.1": exp.PV_RATED_KW},
            voltage_limits=exp.VOLTAGE_LIMITS,
            line_loading_limit=exp.LINE_LIMIT,
            constraint_tolerance=AC_CONSTRAINT_TOLERANCE,
        )
        for day in selected:
            day = int(day)
            ld = load[day, :HORIZON_INTERVALS, 0]
            pv_d = pv[day, :HORIZON_INTERVALS, 0]
            charge, export, reasons = _bounds(feeder, ld, pv_d, site)
            baseline_feasible = int(len(reasons) == 0)
            for interval in range(HORIZON_INTERVALS):
                bound_rows.append(
                    {
                        "date": str(dates[day]),
                        "day_index": day,
                        "group": 0,
                        "site": site,
                        "interval": interval,
                        "charge_limit_kw": float(charge[interval]),
                        "export_limit_kw": float(export[interval]),
                    }
                )
            common = dict(
                charge_limit_kw=charge,
                export_limit_kw=export,
                load_kw=ld,
                service_windows=WINDOWS,
                recovery_windows=FIXED_RECOVERY_WINDOWS,
                energy_kwh=BATTERY_ENERGY_KWH,
                initial_soc=exp.SOC_INITIAL,
                terminal_soc_target=exp.SOC_INITIAL,
                soc_min=exp.SOC_RESERVE,
                soc_max=1.0,
                eta_charge=exp.ETA_CHARGE,
                eta_discharge=exp.ETA_DISCHARGE,
                dt_h=exp.DT_H,
                terminal_mode="exact",
            )
            modes = {
                "network_lp": {"mode": "network_lp"},
                "fixed_recovery": {"mode": "fixed_recovery", "fixed_recovery_ratio": REARM_RATIO},
                "myopic_recovery": {"mode": "myopic_recovery"},
                "energy_only": {"mode": "energy_only"},
            }
            for method, kwargs in modes.items():
                result = plan_service(**common, **kwargs)
                replay_ok, audits = _replay(feeder, ld, pv_d, site, result)
                rows.append(
                    {
                        "date": str(dates[day]),
                        "day_index": day,
                        "group": 0,
                        "site": site,
                        "method": method,
                        "service_kw": float(result.service_kw),
                        "planner_feasible": int(result.feasible),
                        "replay_feasible": int(replay_ok),
                        "baseline_feasible": baseline_feasible,
                        "terminal_soc": float(result.terminal_soc),
                        "max_vmax": float(max((a.vmax for a in audits if np.isfinite(a.vmax)), default=np.nan)),
                        "max_loading": float(max((a.max_line_loading for a in audits if np.isfinite(a.max_line_loading)), default=np.nan)),
                        "message": result.message,
                    }
                )
                if day == int(selected[0]) and site == sites[0]:
                    trace_rows.extend(
                        {
                            "interval": interval,
                            "method": method,
                            "charge_kw": float(result.charge_kw[interval]),
                            "discharge_kw": float(result.discharge_kw[interval]),
                            "soc": float(result.soc[interval]),
                            "grid_import_kw": float(result.grid_import_kw[interval]),
                            "charge_limit_kw": float(charge[interval]),
                            "export_limit_kw": float(export[interval]),
                        }
                        for interval in range(HORIZON_INTERVALS)
                    )

    out_dir.mkdir(parents=True, exist_ok=True)
    policy = pd.DataFrame(rows)
    bounds = pd.DataFrame(bound_rows)
    trace = pd.DataFrame(trace_rows)
    policy.to_csv(out_dir / "policy_rows.csv", index=False)
    bounds.to_csv(out_dir / "ac_bounds.csv", index=False)
    trace.to_csv(out_dir / "representative_trace.csv", index=False)
    grouped = policy.groupby(["site", "method"], as_index=False).agg(
        mean_service_kw=("service_kw", "mean"),
        median_service_kw=("service_kw", "median"),
        replay_success=("replay_feasible", "mean"),
        baseline_success=("baseline_feasible", "mean"),
        n=("service_kw", "size"),
    )
    conditional = (
        policy[policy.baseline_feasible == 1]
        .groupby(["site", "method"], as_index=False)
        .agg(
            conditional_mean_service_kw=("service_kw", "mean"),
            conditional_median_service_kw=("service_kw", "median"),
            conditional_replay_success=("replay_feasible", "mean"),
            n_baseline=("service_kw", "size"),
        )
    )
    summary: dict[str, object] = {
        "status": "opsd_cross_source_strict_v5",
        "source": str(source),
        "source_sha256": sha256(source),
        "sites": list(sites),
        "n_days": int(len(selected)),
        "selected_dates": [str(dates[int(i)]) for i in selected],
        "n_profile_groups": 1,
        "profile_processing": profile_meta,
        "embedding": {
            "load_offset": exp.LOAD_OFFSET,
            "load_gain": exp.LOAD_GAIN,
            "load_clip": [0.35, 0.85],
            "pv_offset": exp.PV_OFFSET,
            "pv_gain": exp.PV_GAIN,
            "pv_clip": [0.0, 1.0],
            "train_only_scales": True,
            "pv_site": "675.1",
            "pv_rated_kw": exp.PV_RATED_KW,
        },
        "protocol": {
            "horizon_intervals": HORIZON_INTERVALS,
            "service_windows": [list(x) for x in WINDOWS],
            "fixed_recovery_windows": [list(x) for x in FIXED_RECOVERY_WINDOWS],
            "fixed_recovery_ratio": REARM_RATIO,
            "battery_energy_kwh": BATTERY_ENERGY_KWH,
            "line_limit": exp.LINE_LIMIT,
            "voltage_limits_pu": list(exp.VOLTAGE_LIMITS),
            "controls_off": True,
            "battery_q_kvar": 0.0,
            "selection": "calendar-spread held-out OPSD test dates chosen before AC evaluation",
        },
        "summary": grouped.to_dict(orient="records"),
        "conditional_summary": conditional.to_dict(orient="records"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-days", type=int, default=0, help="0=all held-out OPSD test dates")
    parser.add_argument("--sites", type=str, default=','.join(DEFAULT_SITES))
    args = parser.parse_args()
    chosen_sites = tuple(x.strip() for x in args.sites.split(',') if x.strip())
    print(json.dumps(run(args.source, args.out_dir, args.max_days, chosen_sites), indent=2))
