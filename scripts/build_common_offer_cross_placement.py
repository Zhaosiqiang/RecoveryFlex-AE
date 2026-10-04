#!/usr/bin/env python3
"""Evaluate one fixed common offer across the seven battery placements.

The offer is selected once from the 2012 calibration block as the lower
5th-percentile AC-bound scalar-LP frontier among baseline-AC-feasible units.  The
same kW value is then planned and replayed on every baseline-gated 2013
date--group--site unit.  This is a temporal decision experiment: no site,
date, or capacity retuning is permitted after calibration.

The script writes a planned-run metadata file before the first fixed-offer
dispatch.  Per-site row files are flushed after each site so a long run is
recoverable and its state is visible without treating a partial run as final.
The resulting endpoint is a screening result for the retained date blocks;
it is not a probability guarantee for future feeder conditions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from recoveryflex.ac_snapshot import ACSnapshotFeeder
from recoveryflex.dispatch import plan_service
from recoveryflex.profile_bank import load_bank
import run_corrected_experiment as exp
from cluster_statistics import cluster_bootstrap
from run_network_recovery_v2 import (
    _embedded_external,
    _replay,
    WINDOWS,
    FIXED_RECOVERY_WINDOWS,
    BATTERY_ENERGY_KWH,
    AC_CONSTRAINT_TOLERANCE,
)


SITES = ("611.3", "634.1", "675.1", "652.1", "645.3", "646.3", "684.3")
HORIZON_INTERVALS = 48
CALIBRATION_YEAR = "2012"
EVALUATION_YEAR = "2013"
TARGET_COVERAGE = 0.95
LOWER_TAIL = 1.0 - TARGET_COVERAGE
BOOTSTRAP_REPLICATES = 5000
BOOTSTRAP_SEED = 20261004

DEFAULT_RESULTS = ROOT / "results" / "location_sensitivity_external_2012_2013_strict_v4"
DEFAULT_OUT = ROOT / "results" / "common_offer_cross_placement_strict_v6"
DEFAULT_SOURCE = ROOT / "data" / "processed" / "ausgrid_external_2012_2013_strict.npz"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(value: object) -> object:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"cannot encode {type(value)!r}")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=_json_default) + "\n")


def _validate_policy_rows(rows: pd.DataFrame, sites: tuple[str, ...]) -> pd.DataFrame:
    required = {
        "date", "day_index", "group", "site", "method", "service_kw",
        "baseline_feasible",
    }
    missing = sorted(required - set(rows.columns))
    if missing:
        raise ValueError(f"policy_rows.csv missing required columns: {missing}")
    out = rows.copy()
    out["date"] = out["date"].astype(str)
    out["site"] = out["site"].astype(str)
    for col in ("day_index", "group", "service_kw", "baseline_feasible"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if out[col].isna().any() or not np.isfinite(out[col].to_numpy(float)).all():
            raise ValueError(f"{col} contains missing or non-finite values")
    out["day_index"] = out["day_index"].astype(int)
    out["group"] = out["group"].astype(int)
    out["baseline_feasible"] = out["baseline_feasible"].astype(int)
    if not out["baseline_feasible"].isin([0, 1]).all():
        raise ValueError("baseline_feasible must be binary")
    observed = set(out["site"])
    if observed != set(sites):
        raise ValueError(f"site set differs from predeclared seven sites: {sorted(observed)}")
    out = out[out["method"].astype(str) == "network_lp"].copy()
    if out.empty:
        raise ValueError("network_lp rows are absent")
    key = ["date", "day_index", "group", "site"]
    if out.duplicated(key).any():
        raise ValueError("duplicate network_lp rows for date x group x site")
    return out.sort_values(key).reset_index(drop=True)


def _build_bounds_lookup(bounds: pd.DataFrame, eval_keys: pd.DataFrame) -> dict[tuple[int, int, str], tuple[np.ndarray, np.ndarray]]:
    required = {
        "date", "day_index", "group", "site", "interval",
        "charge_limit_kw", "export_limit_kw",
    }
    missing = sorted(required - set(bounds.columns))
    if missing:
        raise ValueError(f"ac_bounds.csv missing required columns: {missing}")
    b = bounds.copy()
    b["date"] = b["date"].astype(str)
    b["site"] = b["site"].astype(str)
    for col in ("day_index", "group", "interval", "charge_limit_kw", "export_limit_kw"):
        b[col] = pd.to_numeric(b[col], errors="coerce")
        if b[col].isna().any() or not np.isfinite(b[col].to_numpy(float)).all():
            raise ValueError(f"{col} in ac_bounds.csv contains missing/non-finite values")
    b[["day_index", "group", "interval"]] = b[["day_index", "group", "interval"]].astype(int)
    lookup: dict[tuple[int, int, str], tuple[np.ndarray, np.ndarray]] = {}
    for key, frame in b.groupby(["day_index", "group", "site"], sort=False):
        frame = frame.sort_values("interval")
        if len(frame) != HORIZON_INTERVALS or not np.array_equal(
            frame["interval"].to_numpy(int), np.arange(HORIZON_INTERVALS)
        ):
            raise ValueError(f"expected 48 consecutive AC-bound rows for {key}")
        lookup[(int(key[0]), int(key[1]), str(key[2]))] = (
            frame["charge_limit_kw"].to_numpy(float),
            frame["export_limit_kw"].to_numpy(float),
        )
    missing_keys = [
        (int(r.day_index), int(r.group), str(r.site))
        for r in eval_keys.itertuples(index=False)
        if (int(r.day_index), int(r.group), str(r.site)) not in lookup
    ]
    if missing_keys:
        raise ValueError(f"AC bounds missing {len(missing_keys)} evaluation units; first={missing_keys[:3]}")
    return lookup


def _date_summary(frame: pd.DataFrame, value: str, context: tuple[object, ...]) -> dict[str, object]:
    result = cluster_bootstrap(
        frame,
        value,
        ("date",),
        BOOTSTRAP_SEED,
        BOOTSTRAP_REPLICATES,
        context=context + ("date",),
        count_name="n_dates",
    )
    return result


def _make_summary(rows: pd.DataFrame, offer_kw: float) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    rows = rows.copy()
    rows["year"] = rows["date"].str[:4]
    records: list[dict[str, object]] = []
    for population, frame in (("pooled", rows),):
        for site in ("pooled", *SITES):
            part = frame if site == "pooled" else frame[frame["site"] == site]
            if part.empty:
                continue
            for outcome in ("planner_feasible", "replay_feasible", "frontier_meets_offer"):
                result = _date_summary(part, outcome, ("common_offer", population, site, outcome))
                records.append({
                    "population": population,
                    "site": site,
                    "outcome": outcome,
                    "cluster_level": "date",
                    **result,
                })
    stats = pd.DataFrame(records)

    site_rows: list[dict[str, object]] = []
    for site in ("pooled", *SITES):
        part = rows if site == "pooled" else rows[rows.site == site]
        if part.empty:
            continue
        site_rows.append({
            "site": site,
            "threshold_kw": float(offer_kw),
            "n_units": int(len(part)),
            "n_dates": int(part.date.nunique()),
            "planner_feasible": int(part.planner_feasible.sum()),
            "replay_feasible": int(part.replay_feasible.sum()),
            "frontier_meets_offer": int(part.frontier_meets_offer.sum()),
            "planner_feasible_rate": float(part.planner_feasible.mean()),
            "replay_feasible_rate": float(part.replay_feasible.mean()),
            "frontier_meets_offer_rate": float(part.frontier_meets_offer.mean()),
            "mean_local_frontier_kw": float(part.local_frontier_kw.mean()),
            "p05_local_frontier_kw": float(np.quantile(part.local_frontier_kw, 0.05, method="linear")),
            "mean_shortfall_kw": float(part.shortfall_kw.mean()),
            "total_shortfall_kw": float(part.shortfall_kw.sum()),
        })
    site_summary = pd.DataFrame(site_rows)
    date_summary = stats.copy()
    summary: dict[str, object] = {
        "status": "common_offer_cross_placement_strict_v6_complete",
        "threshold_kw": float(offer_kw),
        "threshold_selection": {
            "calibration_year": CALIBRATION_YEAR,
            "population": "baseline-AC-feasible network_lp frontier units across seven sites",
            "quantile": TARGET_COVERAGE,
            "quantile_convention": "numpy linear interpolation at lower_tail = 0.05",
            "no_site_retuning": True,
            "no_evaluation_data_used_for_threshold": True,
        },
        "evaluation_year": EVALUATION_YEAR,
        "n_units": int(len(rows)),
        "n_dates": int(rows.date.nunique()),
        "sites": list(SITES),
        "primary_estimands": {
            "planner_feasible_rate": _date_summary(rows, "planner_feasible", ("common_offer", "primary", "planner")),
            "replay_feasible_rate": _date_summary(rows, "replay_feasible", ("common_offer", "primary", "replay")),
            "frontier_meets_offer_rate": _date_summary(rows, "frontier_meets_offer", ("common_offer", "primary", "frontier")),
        },
        "interpretation": "A fixed screening offer replayed through the nonlinear feeder on the retained 2013 block; this is not a future probability guarantee.",
    }
    return summary, site_summary, date_summary


def _plot(rows: pd.DataFrame, offer_kw: float, out_dir: Path) -> None:
    import matplotlib.pyplot as plt

    grouped = rows.groupby("site", sort=False)
    sites = [s for s in SITES if s in grouped.groups]
    rates = [float(grouped.get_group(s).replay_feasible.mean()) * 100.0 for s in sites]
    p05 = [float(np.quantile(grouped.get_group(s).local_frontier_kw, 0.05, method="linear")) for s in sites]
    mean = [float(grouped.get_group(s).local_frontier_kw.mean()) for s in sites]
    colors = ["#0072B2" if r >= 99.0 else "#D55E00" for r in rates]
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(11.4, 4.3), constrained_layout=True)
    x = np.arange(len(sites))
    ax0.bar(x, rates, color=colors, width=0.68)
    ax0.axhline(95.0, color="#444444", linestyle="--", linewidth=1.2, label="95% reference")
    ax0.set_ylim(0, 102)
    ax0.set_ylabel("2013 nonlinear-replay feasibility (%)")
    ax0.set_xlabel("Battery placement (IEEE-13 bus.phase)")
    ax0.set_xticks(x, sites, rotation=35, ha="right")
    ax0.set_title("A. One common offer, no site retuning")
    ax0.grid(axis="y", alpha=0.25)
    ax0.legend(frameon=False, fontsize=8, loc="lower left")
    for xi, val in zip(x, rates):
        ax0.text(xi, min(val + 1.3, 100.5), f"{val:.1f}", ha="center", va="bottom", fontsize=8)

    ax1.scatter(x, mean, color="#4C4C4C", s=32, label="mean local frontier", zorder=3)
    ax1.scatter(x, p05, color="#D55E00", s=42, marker="D", label="local lower 5th percentile", zorder=4)
    ax1.axhline(offer_kw, color="#0072B2", linewidth=2.0, label=f"common offer = {offer_kw:.1f} kW")
    ax1.set_ylabel("AC-bound LP frontier (kW)")
    ax1.set_xlabel("Battery placement (IEEE-13 bus.phase)")
    ax1.set_xticks(x, sites, rotation=35, ha="right")
    ax1.set_title("B. Calibration offer against local 2013 frontiers")
    ax1.grid(axis="y", alpha=0.25)
    ax1.legend(frameon=False, fontsize=8, loc="best")
    for axis in (ax0, ax1):
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)
    fig.savefig(out_dir / "common_offer_cross_placement.png", dpi=320, bbox_inches="tight")
    fig.savefig(out_dir / "common_offer_cross_placement.pdf", bbox_inches="tight")
    plt.close(fig)


def _planned_metadata(
    out_dir: Path,
    source: Path,
    results_dir: Path,
    policy_path: Path,
    bounds_path: Path,
    source_dates: np.ndarray,
    calibration: pd.DataFrame,
    evaluation: pd.DataFrame,
    offer_kw: float,
) -> dict[str, object]:
    return {
        "status": "planned_before_fixed_offer_evaluation",
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": str(source),
        "source_sha256": _sha256(source),
        "results_dir": str(results_dir),
        "policy_rows": str(policy_path),
        "policy_rows_sha256": _sha256(policy_path),
        "ac_bounds": str(bounds_path),
        "ac_bounds_sha256": _sha256(bounds_path),
        "source_date_count": int(len(source_dates)),
        "source_dates_sha256": hashlib.sha256("\n".join(map(str, source_dates)).encode()).hexdigest(),
        "calibration_year": CALIBRATION_YEAR,
        "evaluation_year": EVALUATION_YEAR,
        "calibration_dates": sorted(calibration.date.unique().tolist()),
        "evaluation_dates": sorted(evaluation.date.unique().tolist()),
        "sites": list(SITES),
        "threshold_kw": float(offer_kw),
        "threshold_rule": "linear lower 5th percentile of baseline-AC-feasible 2012 network_lp service_kw, pooled across seven sites; each date-group-site unit counted once",
        "target_empirical_coverage": TARGET_COVERAGE,
        "calibration_units": int(len(calibration)),
        "evaluation_units_before_gate": int(len(evaluation)),
        "evaluation_units_after_baseline_gate": int(evaluation.baseline_feasible.sum()),
        "no_site_retuning": True,
        "no_evaluation_data_used_for_threshold": True,
        "service_windows": [list(x) for x in WINDOWS],
        "recovery_windows": [list(x) for x in FIXED_RECOVERY_WINDOWS],
        "battery_energy_kwh": BATTERY_ENERGY_KWH,
        "ac_constraint_tolerance": AC_CONSTRAINT_TOLERANCE,
        "protocol": "fixed service_power_kw in chronological network_lp, then nonlinear OpenDSS replay",
    }


def run(
    results_dir: Path = DEFAULT_RESULTS,
    out_dir: Path = DEFAULT_OUT,
    source: Path = DEFAULT_SOURCE,
    sites: tuple[str, ...] = SITES,
    overwrite: bool = False,
    eval_date_limit: int | None = None,
    eval_group_limit: int | None = None,
) -> dict[str, object]:
    if tuple(sites) != SITES:
        raise ValueError("E1 requires the predeclared seven-site set; use --dry-run for a subset")
    policy_path = results_dir / "policy_rows.csv"
    bounds_path = results_dir / "ac_bounds.csv"
    for path in (policy_path, bounds_path, source):
        if not path.exists():
            raise FileNotFoundError(path)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "threshold_metadata.json"
    if state_path.exists() and not overwrite:
        state = json.loads(state_path.read_text())
        if state.get("status") == "common_offer_cross_placement_strict_v6_complete":
            raise FileExistsError(f"completed output exists: {out_dir}; pass --overwrite to rerun")

    policy = _validate_policy_rows(pd.read_csv(policy_path), SITES)
    dates = np.load(source, allow_pickle=False)["dates"].astype(str)
    if not np.array_equal(dates, np.sort(dates)):
        raise ValueError("source dates are not sorted; day-index/date pairing would be ambiguous")
    date_to_index = {str(date): i for i, date in enumerate(dates)}
    if policy["date"].map(date_to_index.get).isna().any():
        raise ValueError("policy date is missing from source date vector")

    cal = policy[(policy.date.str[:4] == CALIBRATION_YEAR) & (policy.baseline_feasible == 1)].copy()
    if len(cal) == 0:
        raise ValueError("no baseline-gated calibration units")
    offer_kw = float(np.quantile(cal.service_kw.to_numpy(float), LOWER_TAIL, method="linear"))
    eval_all = policy[policy.date.str[:4] == EVALUATION_YEAR].copy()
    eval_rows = eval_all[eval_all.baseline_feasible == 1].copy()
    if len(eval_rows) == 0:
        raise ValueError("no baseline-gated evaluation units")
    if not np.isfinite(offer_kw) or offer_kw < 0:
        raise ValueError("calibration offer is not finite and non-negative")
    # Optional limits are only for a transparent smoke run.  They are applied
    # after the frozen year split and baseline gate and are recorded in the
    # pre-run metadata; the default full run leaves both limits unset.
    if eval_date_limit is not None:
        if eval_date_limit <= 0:
            raise ValueError("eval_date_limit must be positive")
        dates_keep = sorted(eval_rows.date.unique())[: int(eval_date_limit)]
        eval_rows = eval_rows[eval_rows.date.isin(dates_keep)].copy()
    if eval_group_limit is not None:
        if eval_group_limit <= 0:
            raise ValueError("eval_group_limit must be positive")
        groups_keep = sorted(eval_rows.group.unique())[: int(eval_group_limit)]
        eval_rows = eval_rows[eval_rows.group.isin(groups_keep)].copy()
    if eval_rows.empty:
        raise ValueError("evaluation limits removed all baseline-gated units")
    metadata = _planned_metadata(
        out_dir, source, results_dir, policy_path, bounds_path, dates, cal, eval_all, offer_kw
    )
    metadata["evaluation_selection"] = {
        "date_limit": eval_date_limit,
        "group_limit": eval_group_limit,
        "selected_dates": sorted(eval_rows.date.unique().tolist()),
        "selected_groups": sorted(int(x) for x in eval_rows.group.unique()),
        "selected_units_after_baseline_gate": int(len(eval_rows)),
    }
    metadata["calibration_frontier_min_kw"] = float(cal.service_kw.min())
    metadata["calibration_frontier_max_kw"] = float(cal.service_kw.max())
    metadata["calibration_frontier_mean_kw"] = float(cal.service_kw.mean())
    _write_json(state_path, metadata)

    bank = load_bank(exp.BANK_PATH)
    load, pv, source_dates = _embedded_external(bank, source)
    bounds = pd.read_csv(bounds_path)
    lookup = _build_bounds_lookup(bounds, eval_rows)
    common_base = dict(
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
        mode="network_lp",
        service_power_kw=offer_kw,
    )

    started = time.time()
    all_rows: list[pd.DataFrame] = []
    for site_i, site in enumerate(SITES, 1):
        feeder = ACSnapshotFeeder(
            exp.FEEDER_PATH,
            battery_sites=(site,),
            pv_sites={"675.1": exp.PV_RATED_KW},
            voltage_limits=exp.VOLTAGE_LIMITS,
            line_loading_limit=exp.LINE_LIMIT,
            constraint_tolerance=AC_CONSTRAINT_TOLERANCE,
        )
        site_eval = eval_rows[eval_rows.site == site].sort_values(["day_index", "group"])
        rows: list[dict[str, object]] = []
        for r in site_eval.itertuples(index=False):
            day, group = int(r.day_index), int(r.group)
            charge, export = lookup[(day, group, site)]
            ld, pv_d = load[day, :HORIZON_INTERVALS, group], pv[day, :HORIZON_INTERVALS, group]
            result = plan_service(
                charge_limit_kw=charge,
                export_limit_kw=export,
                load_kw=ld,
                **common_base,
            )
            replay_ok, audits = _replay(feeder, ld, pv_d, site, result)
            finite_v = [a.vmax for a in audits if np.isfinite(a.vmax)]
            finite_l = [a.max_line_loading for a in audits if np.isfinite(a.max_line_loading)]
            local_frontier = float(r.service_kw)
            rows.append({
                "date": str(r.date),
                "day_index": day,
                "group": group,
                "site": site,
                "threshold_kw": offer_kw,
                "local_frontier_kw": local_frontier,
                "frontier_meets_offer": int(local_frontier + 1e-9 >= offer_kw),
                "shortfall_kw": max(0.0, offer_kw - local_frontier),
                "planner_feasible": int(result.feasible),
                "replay_feasible": int(replay_ok),
                "terminal_soc": float(result.terminal_soc),
                "max_vmax": float(max(finite_v, default=np.nan)),
                "max_loading": float(max(finite_l, default=np.nan)),
                "message": result.message,
            })
        site_frame = pd.DataFrame(rows)
        site_frame.to_csv(out_dir / f"rows_{site.replace('.', '_')}.csv", index=False)
        all_rows.append(site_frame)
        print(
            f"[{site_i}/{len(SITES)}] {site}: n={len(site_frame)} "
            f"planner={site_frame.planner_feasible.mean():.6f} "
            f"replay={site_frame.replay_feasible.mean():.6f} "
            f"elapsed={time.time() - started:.1f}s",
            flush=True,
        )

    out = pd.concat(all_rows, ignore_index=True)
    out = out.sort_values(["date", "day_index", "group", "site"]).reset_index(drop=True)
    out.to_csv(out_dir / "rows.csv", index=False)
    summary, site_summary, date_summary = _make_summary(out, offer_kw)
    site_summary.to_csv(out_dir / "site_summary.csv", index=False)
    date_summary.to_csv(out_dir / "date_cluster_summary.csv", index=False)
    _plot(out, offer_kw, out_dir)

    metadata.update({
        "status": "common_offer_cross_placement_strict_v6_complete",
        "completed_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_seconds": float(time.time() - started),
        "rows_sha256": _sha256(out_dir / "rows.csv"),
        "n_evaluation_rows": int(len(out)),
        "all_planner_feasible": bool(out.planner_feasible.all()),
        "all_replay_feasible": bool(out.replay_feasible.all()),
    })
    _write_json(state_path, metadata)
    _write_json(out_dir / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--eval-date-limit", type=int, default=None,
                        help="smoke-run limit on sorted 2013 dates after baseline gate")
    parser.add_argument("--eval-group-limit", type=int, default=None,
                        help="smoke-run limit on sorted profile groups after baseline gate")
    args = parser.parse_args()
    print(json.dumps(run(
        args.results_dir, args.out_dir, args.source, SITES, args.overwrite,
        args.eval_date_limit, args.eval_group_limit,
    ), indent=2))


if __name__ == "__main__":
    main()
