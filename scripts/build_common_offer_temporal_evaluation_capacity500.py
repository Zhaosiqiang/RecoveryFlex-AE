#!/usr/bin/env python3
"""Strict capacity-500 cross-placement common-offer evaluation.

This is an additive falsification experiment for v5/E1.  It recalculates the
AC-bound LP endpoint at E=500 kWh for all seven predeclared sites, selects one
pooled lower-5th-percentile offer from the retained 2012 calibration block,
and evaluates that fixed offer on retained 2013 units with the exact terminal
SOC and the same interval OpenDSS replay used by E1.  A service-window export
floor (B_svc) offer is evaluated in parallel as a comparator.  No existing
v5 result directory is modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from recoveryflex.ac_snapshot import ACSnapshotFeeder  # noqa: E402
from recoveryflex.dispatch import plan_service  # noqa: E402
from recoveryflex.profile_bank import load_bank  # noqa: E402
import run_corrected_experiment as exp  # noqa: E402
from cluster_statistics import cluster_bootstrap  # noqa: E402
from run_network_recovery_v2 import (  # noqa: E402
    _embedded_external,
    _replay,
    AC_CONSTRAINT_TOLERANCE,
    BATTERY_ENERGY_KWH,
    FIXED_RECOVERY_WINDOWS,
    WINDOWS,
)

SITES = ("611.3", "634.1", "675.1", "652.1", "645.3", "646.3", "684.3")
CALIBRATION_YEAR = "2012"
EVALUATION_YEAR = "2013"
ENERGY_KWH = 500.0
TARGET_COVERAGE = 0.95
BOOT_SEED = 20261003
N_BOOT = 5000
SERVICE_INTERVALS = tuple(range(8, 12)) + tuple(range(24, 28))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def _load_bounds(path: Path, site: str) -> dict[tuple[int, int], tuple[np.ndarray, np.ndarray]]:
    frame = pd.read_csv(path)
    frame["site"] = frame["site"].astype(str)
    frame = frame[frame.site == str(site)]
    out: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
    for (day, group), g in frame.groupby(["day_index", "group"], sort=False):
        g = g.sort_values("interval")
        if len(g) != 48 or not np.array_equal(g.interval.to_numpy(), np.arange(48)):
            raise ValueError(f"expected 48 ordered rows for {site}/{day}/{group}")
        out[(int(day), int(group))] = (
            g.charge_limit_kw.to_numpy(float),
            g.export_limit_kw.to_numpy(float),
        )
    return out


def _bsvc(export: np.ndarray) -> float:
    return float(np.min(export[list(SERVICE_INTERVALS)]))


def _plan_endpoint(charge: np.ndarray, export: np.ndarray, load: np.ndarray, energy_kwh: float) -> tuple[float, bool, str]:
    result = plan_service(
        charge_limit_kw=charge,
        export_limit_kw=export,
        load_kw=load,
        service_windows=WINDOWS,
        recovery_windows=FIXED_RECOVERY_WINDOWS,
        energy_kwh=energy_kwh,
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
    return float(result.service_kw), bool(result.feasible), str(result.message)


def _calibration_site(site: str, primary: str, source: str) -> pd.DataFrame:
    primary_path, source_path = Path(primary), Path(source)
    policy = pd.read_csv(primary_path / "policy_rows.csv")
    policy["site"] = policy.site.astype(str)
    policy = policy[(policy.site == str(site)) & (policy.method == "network_lp")]
    policy = policy[policy.baseline_feasible.astype(int) == 1]
    policy["year"] = policy.date.astype(str).str[:4]
    policy = policy[policy.year == CALIBRATION_YEAR].copy()
    if policy.empty:
        raise ValueError(f"no calibration units for {site}")
    bounds = _load_bounds(primary_path / "ac_bounds.csv", site)
    bank = load_bank(exp.BANK_PATH)
    load, _pv, dates = _embedded_external(bank, source_path)
    rows: list[dict[str, Any]] = []
    for r in policy.sort_values(["day_index", "group"]).itertuples(index=False):
        charge, export = bounds[(int(r.day_index), int(r.group))]
        endpoint, feasible, message = _plan_endpoint(
            charge, export, load[int(r.day_index), :48, int(r.group)], ENERGY_KWH
        )
        if not feasible:
            endpoint = 0.0
        rows.append(
            {
                "date": str(r.date),
                "year": str(r.year),
                "day_index": int(r.day_index),
                "group": int(r.group),
                "site": str(site),
                "network_lp_e500_kw": endpoint,
                "network_lp_e500_feasible": int(feasible),
                "network_lp_e500_message": message,
                "b_svc_kw": _bsvc(export),
            }
        )
    return pd.DataFrame(rows)


def _failure_class(result: Any, audits: list[Any]) -> str:
    if not bool(result.feasible):
        msg = str(result.message)
        if "export limit" in msg:
            return "planner_export_limit"
        if "terminal" in msg.lower() or "infeasible" in msg.lower():
            return "planner_soc_or_terminal"
        return "planner_infeasible"
    if not audits:
        return "replay_no_audits"
    reasons: set[str] = set()
    for audit in audits:
        if not audit.feasible:
            reasons.update(str(x) for x in audit.failure_reasons)
            if not audit.converged:
                reasons.add("nonconverged")
    if not reasons:
        reasons.add("replay_feasibility_false")
    if any("voltage" in x.lower() for x in reasons):
        return "replay_voltage"
    if any("transformer" in x.lower() or "line" in x.lower() or "loading" in x.lower() for x in reasons):
        return "replay_loading"
    if "nonconverged" in reasons:
        return "replay_nonconvergence"
    return "replay_other"


def _evaluate_site(site: str, primary: str, source: str, network_offer: float, b_offer: float) -> pd.DataFrame:
    primary_path, source_path = Path(primary), Path(source)
    policy = pd.read_csv(primary_path / "policy_rows.csv")
    policy["site"] = policy.site.astype(str)
    policy = policy[(policy.site == str(site)) & (policy.method == "network_lp")]
    policy["year"] = policy.date.astype(str).str[:4]
    policy = policy[(policy.year == EVALUATION_YEAR) & (policy.baseline_feasible.astype(int) == 1)].copy()
    if policy.empty:
        raise ValueError(f"no evaluation units for {site}")
    bounds = _load_bounds(primary_path / "ac_bounds.csv", site)
    bank = load_bank(exp.BANK_PATH)
    load, pv, dates = _embedded_external(bank, source_path)
    feeder = ACSnapshotFeeder(
        exp.FEEDER_PATH,
        battery_sites=(str(site),),
        pv_sites={"675.1": exp.PV_RATED_KW},
        voltage_limits=exp.VOLTAGE_LIMITS,
        line_loading_limit=exp.LINE_LIMIT,
        constraint_tolerance=AC_CONSTRAINT_TOLERANCE,
    )
    rows: list[dict[str, Any]] = []
    for offer_kind, offer in (("network_lp_e500", network_offer), ("b_svc", b_offer)):
        for r in policy.sort_values(["day_index", "group"]).itertuples(index=False):
            day, group = int(r.day_index), int(r.group)
            charge, export = bounds[(day, group)]
            result = plan_service(
                charge_limit_kw=charge,
                export_limit_kw=export,
                load_kw=load[day, :48, group],
                service_windows=WINDOWS,
                recovery_windows=FIXED_RECOVERY_WINDOWS,
                energy_kwh=ENERGY_KWH,
                initial_soc=exp.SOC_INITIAL,
                terminal_soc_target=exp.SOC_INITIAL,
                soc_min=exp.SOC_RESERVE,
                soc_max=1.0,
                eta_charge=exp.ETA_CHARGE,
                eta_discharge=exp.ETA_DISCHARGE,
                dt_h=exp.DT_H,
                terminal_mode="exact",
                mode="network_lp",
                service_power_kw=float(offer),
            )
            if result.feasible:
                replay_ok, audits = _replay(
                    feeder, load[day, :48, group], pv[day, :48, group], str(site), result
                )
                replay_run = 1
                replay_class = "pass" if replay_ok else _failure_class(result, audits)
            else:
                replay_ok, audits, replay_run = False, [], 0
                replay_class = _failure_class(result, audits)
            vmax = max((a.vmax for a in audits if np.isfinite(a.vmax)), default=np.nan)
            loading = max((a.max_line_loading for a in audits if np.isfinite(a.max_line_loading)), default=np.nan)
            max_transformer = max((a.max_transformer_loading for a in audits if np.isfinite(a.max_transformer_loading)), default=np.nan)
            rows.append(
                {
                    "date": str(r.date),
                    "year": str(r.year),
                    "day_index": day,
                    "group": group,
                    "site": str(site),
                    "offer_kind": offer_kind,
                    "offer_kw": float(offer),
                    "planner_feasible": int(result.feasible),
                    "replay_feasible": int(replay_ok),
                    "replay_run": replay_run,
                    "joint_success": int(result.feasible and replay_ok),
                    "terminal_soc": float(result.terminal_soc),
                    "max_vmax": float(vmax),
                    "max_loading": float(loading),
                    "max_transformer_loading": float(max_transformer),
                    "replay_class": replay_class,
                    "message": str(result.message),
                    "local_bsvc_kw": _bsvc(export),
                }
            )
    return pd.DataFrame(rows)


def _summary(rows: pd.DataFrame, context: tuple[Any, ...]) -> dict[str, Any]:
    rows = rows.copy()
    out: dict[str, Any] = {"context": list(context), "n_units": int(len(rows)), "n_dates": int(rows.date.nunique())}
    for value in ("joint_success", "planner_feasible", "replay_feasible"):
        out[value] = cluster_bootstrap(
            rows, value, ("date",), BOOT_SEED, N_BOOT,
            context=(*context, value), count_name="n_dates",
        )
    # Keep unit-weighted estimands alongside the canonical date-cluster estimand.
    out["unit_weighted"] = {
        value: float(pd.to_numeric(rows[value], errors="raise").mean())
        for value in ("joint_success", "planner_feasible", "replay_feasible")
    }
    out["failure_class_counts"] = rows.loc[rows.joint_success == 0, "replay_class"].value_counts().to_dict()
    return out


def run(
    primary: Path = ROOT / "results/location_sensitivity_external_2012_2013_strict_v4",
    source: Path = ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz",
    out_dir: Path = ROOT / "results/common_offer_temporal_evaluation_capacity500_strict_v1",
    workers: int | None = None,
) -> dict[str, Any]:
    primary = primary.resolve()
    source = source.resolve()
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Stage 1: recalculate E=500 network frontiers on the seven-site 2012 block.
    cal_frames: list[pd.DataFrame] = []
    max_workers = int(workers or min(len(SITES), os.cpu_count() or 1))
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_calibration_site, site, str(primary), str(source)): site for site in SITES}
        for future in as_completed(futures):
            cal_frames.append(future.result())
    calibration = pd.concat(cal_frames, ignore_index=True).sort_values(["site", "day_index", "group"]).reset_index(drop=True)
    if calibration.duplicated(["date", "group", "site"]).any():
        raise ValueError("duplicate calibration units")
    network_offer = float(np.quantile(calibration.network_lp_e500_kw.to_numpy(float), 1.0 - TARGET_COVERAGE, method="linear"))
    b_offer = float(np.quantile(calibration.b_svc_kw.to_numpy(float), 1.0 - TARGET_COVERAGE, method="linear"))
    calibration.to_csv(out_dir / "calibration_rows.csv", index=False)

    # Stage 2: evaluate both fixed offers using exact terminal SOC and AC replay.
    eval_frames: list[pd.DataFrame] = []
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_evaluate_site, site, str(primary), str(source), network_offer, b_offer): site
            for site in SITES
        }
        for future in as_completed(futures):
            eval_frames.append(future.result())
    rows = pd.concat(eval_frames, ignore_index=True).sort_values(["offer_kind", "site", "day_index", "group"]).reset_index(drop=True)
    if rows.duplicated(["date", "group", "site", "offer_kind"]).any():
        raise ValueError("duplicate evaluation units")
    rows.to_csv(out_dir / "rows.csv", index=False)
    rows[rows.joint_success == 0].to_csv(out_dir / "failure_records.csv", index=False)

    site_records: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    for offer_kind, g in rows.groupby("offer_kind", sort=True):
        summaries[offer_kind] = _summary(g, ("pooled_evaluation", offer_kind))
        for site, sg in g.groupby("site", sort=True):
            st = _summary(sg, ("site_evaluation", offer_kind, str(site)))
            site_records.append({
                "offer_kind": offer_kind,
                "site": str(site),
                "n_units": int(len(sg)),
                "n_dates": int(sg.date.nunique()),
                "offer_kw": float(sg.offer_kw.iloc[0]),
                "planner_unit_rate": float(sg.planner_feasible.mean()),
                "joint_unit_rate": float(sg.joint_success.mean()),
                "replay_unit_rate_conditional": float(sg.loc[sg.planner_feasible == 1, "replay_feasible"].mean()) if (sg.planner_feasible == 1).any() else float("nan"),
                "planner_date_rate": float(sg.groupby("date").planner_feasible.mean().mean()),
                "joint_date_rate": float(sg.groupby("date").joint_success.mean().mean()),
                "replay_date_rate_conditional": float(sg.loc[sg.planner_feasible == 1].groupby("date").replay_feasible.mean().mean()) if (sg.planner_feasible == 1).any() else float("nan"),
                "joint_ci_low": float(st["joint_success"]["ci_low"]),
                "joint_ci_high": float(st["joint_success"]["ci_high"]),
                "failure_class_counts": json.dumps(st["failure_class_counts"], sort_keys=True),
            })
    site_summary = pd.DataFrame(site_records)
    site_summary.to_csv(out_dir / "site_summary.csv", index=False)

    date_summary = rows.groupby(["offer_kind", "date", "year"], sort=True).agg(
        n_units=("joint_success", "size"),
        planner_rate=("planner_feasible", "mean"),
        joint_rate=("joint_success", "mean"),
        replay_rate_conditional=("replay_feasible", "mean"),
    ).reset_index()
    date_summary.to_csv(out_dir / "date_summary.csv", index=False)

    bank = load_bank(exp.BANK_PATH)
    _load, _pv, dates = _embedded_external(bank, source)
    year = pd.Series(dates.astype(str)).str[:4].to_numpy()
    metadata = {
        "status": "common_offer_temporal_evaluation_capacity500_strict_v1",
        "energy_kwh": ENERGY_KWH,
        "sites": list(SITES),
        "calibration_year": CALIBRATION_YEAR,
        "evaluation_year": EVALUATION_YEAR,
        "target_empirical_coverage": TARGET_COVERAGE,
        "network_lp_calibration_offer_kw": network_offer,
        "b_svc_calibration_offer_kw": b_offer,
        "offer_difference_kw": network_offer - b_offer,
        "calibration_units": int(len(calibration)),
        "evaluation_units_per_offer": int(len(rows) // 2),
        "calibration_dates": int(np.sum(year == CALIBRATION_YEAR)),
        "evaluation_dates": int(np.sum(year == EVALUATION_YEAR)),
        "calibration_date_list": sorted(set(dates[year == CALIBRATION_YEAR].astype(str))),
        "evaluation_date_list": sorted(set(dates[year == EVALUATION_YEAR].astype(str))),
        "calibration_rule": "pooled lower 5th percentile over E=500 AC-bound LP endpoints and B_svc comparator, baseline-AC-gated units, np.quantile(method=linear)",
        "b_svc_definition": "minimum export_limit_kw over the eight service intervals (8:12 and 24:28)",
        "ac_replay": "fixed-power plan_service with exact terminal SOC followed by interval nonlinear OpenDSS replay for every planner-feasible schedule; planner-infeasible rows are retained and marked replay_run=0",
        "seed": BOOT_SEED,
        "n_boot": N_BOOT,
        "script": _relative(Path(__file__)),
        "script_sha256": _sha256(Path(__file__)),
        "source": _relative(source),
        "source_sha256": _sha256(source),
        "processed_metadata": "data/processed/ausgrid_external_2012_2013_strict.json",
        "processed_metadata_sha256": _sha256(ROOT / "data/processed/ausgrid_external_2012_2013_strict.json"),
        "primary_result": "results/location_sensitivity_external_2012_2013_strict_v4",
        "claim_boundary": "capacity-500 temporal screening experiment under the frozen single IEEE-13 feeder, synthetic embedding, selected sites, and ideal active-power battery; not a future guarantee or cross-feeder transfer",
        "calibration_unit_key_unique": True,
        "evaluation_unit_key_unique": True,
    }
    (out_dir / "threshold_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    payload = {"metadata": metadata, "offers": summaries, "site_summary": site_records}
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2) + "\n")

    # Diagnostic figure: offer thresholds and strict joint replay coverage.
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.0, 4.1), constrained_layout=True)
    labels = ["E=500 AC-bound LP", "B_svc floor"]
    offers = [network_offer, b_offer]
    ax1.bar(np.arange(2), offers, color=["#356b8c", "#c44e52"])
    ax1.set_xticks(np.arange(2), labels, rotation=20, ha="right")
    ax1.set_ylabel("2012 calibration offer (kW)")
    ax1.set_title("Fixed pooled offers")
    for x, y in enumerate(offers):
        ax1.text(x, y + 1.0, f"{y:.1f}", ha="center", fontsize=8)
    pooled_rates = [summaries[k]["unit_weighted"]["joint_success"] * 100 for k in ("network_lp_e500", "b_svc")]
    ax2.bar(np.arange(2), pooled_rates, color=["#4c956c", "#8c8c8c"])
    ax2.set_xticks(np.arange(2), labels, rotation=20, ha="right")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("2013 planner + AC replay success (%)")
    ax2.set_title("Retained 2013 evaluation")
    for x, y in enumerate(pooled_rates):
        ax2.text(x, min(99, y + 1.0), f"{y:.2f}", ha="center", fontsize=8)
    fig.savefig(out_dir / "common_offer_temporal_evaluation_capacity500.png", dpi=240)
    fig.savefig(out_dir / "common_offer_temporal_evaluation_capacity500.pdf")
    plt.close(fig)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, default=ROOT / "results/location_sensitivity_external_2012_2013_strict_v4")
    parser.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/common_offer_temporal_evaluation_capacity500_strict_v1")
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    payload = run(args.primary, args.source, args.out_dir, args.workers)
    print(json.dumps(payload["metadata"], indent=2))
