#!/usr/bin/env python3
"""Evaluate one fixed common offer across seven placements by time block.

The calibration block is the retained 2012 portion of the frozen external
protocol.  A single lower-tail AC-bound scalar-LP endpoint quantile is selected from
that block, then the same power is sent to the fixed-power LP and replayed
through nonlinear OpenDSS for every baseline-AC-feasible 2013 unit at all
seven predeclared sites.  The evaluation block is never used to choose the
offer.  This is a temporal screening experiment, not a future guarantee.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
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
    AC_CONSTRAINT_TOLERANCE,
    BATTERY_ENERGY_KWH,
)


SITES = ("611.3", "634.1", "675.1", "652.1", "645.3", "646.3", "684.3")
CALIBRATION_YEAR = "2012"
EVALUATION_YEAR = "2013"
TARGET_COVERAGE = 0.95
BOOT_SEED = 20261003
N_BOOT = 5000


def _source_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _bounds_lookup(path: Path) -> dict[tuple[str, int, int], tuple[np.ndarray, np.ndarray]]:
    frame = pd.read_csv(path)
    frame["site"] = frame["site"].astype(str)
    out: dict[tuple[str, int, int], tuple[np.ndarray, np.ndarray]] = {}
    for (site, day, group), g in frame.groupby(["site", "day_index", "group"], sort=False):
        g = g.sort_values("interval")
        if len(g) != 48 or not np.array_equal(g["interval"].to_numpy(), np.arange(48)):
            raise ValueError(f"expected 48 ordered bound rows for {site}/{day}/{group}")
        out[(str(site), int(day), int(group))] = (
            g["charge_limit_kw"].to_numpy(float),
            g["export_limit_kw"].to_numpy(float),
        )
    return out


def _fixed_rows(
    site: str,
    offer: float,
    evaluation: pd.DataFrame,
    bounds: dict[tuple[str, int, int], tuple[np.ndarray, np.ndarray]],
    load: np.ndarray,
    pv: np.ndarray,
    dates: np.ndarray,
) -> pd.DataFrame:
    feeder = ACSnapshotFeeder(
        exp.FEEDER_PATH,
        battery_sites=(str(site),),
        pv_sites={"675.1": exp.PV_RATED_KW},
        voltage_limits=exp.VOLTAGE_LIMITS,
        line_loading_limit=exp.LINE_LIMIT,
        constraint_tolerance=AC_CONSTRAINT_TOLERANCE,
    )
    rows: list[dict[str, object]] = []
    for r in evaluation.sort_values(["day_index", "group"]).itertuples(index=False):
        day, group = int(r.day_index), int(r.group)
        charge, export = bounds[(str(site), day, group)]
        result = plan_service(
            charge_limit_kw=charge,
            export_limit_kw=export,
            load_kw=load[day, :48, group],
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
            service_power_kw=float(offer),
        )
        replay_ok, audits = _replay(
            feeder, load[day, :48, group], pv[day, :48, group], str(site), result
        )
        vmax = max((a.vmax for a in audits if np.isfinite(a.vmax)), default=np.nan)
        loading = max((a.max_line_loading for a in audits if np.isfinite(a.max_line_loading)), default=np.nan)
        rows.append({
            "date": str(dates[day]),
            "year": str(dates[day])[:4],
            "day_index": day,
            "group": group,
            "site": str(site),
            "common_offer_kw": float(offer),
            "local_endpoint_kw": float(r.service_kw),
            "local_endpoint_minus_common_kw": float(r.service_kw) - float(offer),
            "baseline_feasible": 1,
            "planner_feasible": int(result.feasible),
            "replay_feasible": int(replay_ok),
            "shortfall_kw": float(max(0.0, float(offer) - float(r.service_kw))),
            "shortfall_kwh": float(max(0.0, float(offer) - float(r.service_kw)) * 4.0),
            "terminal_soc": float(result.terminal_soc),
            "max_vmax": float(vmax),
            "max_loading": float(loading),
            "message": result.message,
        })
    return pd.DataFrame(rows)


def _interval_summary(rows: pd.DataFrame, *, context: str) -> dict[str, object]:
    rows = rows.copy()
    rows["success"] = (rows["planner_feasible"].astype(int) & rows["replay_feasible"].astype(int)).astype(float)
    rows["planner_success"] = rows["planner_feasible"].astype(float)
    rows["shortfall_kwh"] = pd.to_numeric(rows["shortfall_kwh"], errors="raise")
    out: dict[str, object] = {"context": context, "n_units": int(len(rows)), "n_dates": int(rows.date.nunique())}
    for value in ("success", "planner_success", "shortfall_kwh"):
        stat = cluster_bootstrap(rows, value, ("date",), BOOT_SEED, N_BOOT, context=(context, value))
        out[value] = stat
    return out


def _plot_evaluation(
    network: pd.DataFrame,
    site_summary: pd.DataFrame,
    offer: float,
    out_dir: Path,
    sites: tuple[str, ...] = SITES,
) -> None:
    """Render the decision figure from recorded endpoints and replay summaries."""
    # One compact decision figure: one offer line against site-local 2013
    # endpoint distributions, with replay coverage on a second axis.
    local = network[(network.year == EVALUATION_YEAR) & (network.baseline_feasible.astype(int) == 1)]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.0, 4.1), constrained_layout=True)
    positions = np.arange(len(sites))
    data = [local[local.site == s].service_kw.to_numpy(float) for s in sites]
    ax1.boxplot(data, positions=positions, widths=0.55, showfliers=False, patch_artist=True,
                boxprops={"facecolor": "#d9e8f5", "edgecolor": "#356b8c"},
                medianprops={"color": "#1b3a4b", "linewidth": 1.5})
    ax1.axhline(offer, color="#c44e52", linestyle="--", linewidth=1.5, label=f"common offer {offer:.1f} kW")
    ax1.set_xticks(positions, sites, rotation=45, ha="right")
    ax1.set_ylabel("2013 AC-bound LP endpoint (kW)")
    ax1.set_title("One offer across placements")
    ax1.legend(frameon=False, fontsize=8)
    rates = site_summary.set_index("site").loc[list(sites), "joint_replay_rate"].to_numpy(float) * 100.0
    ax2.bar(positions, rates, color="#4c956c", alpha=0.85)
    ax2.set_xticks(positions, sites, rotation=45, ha="right")
    # Leave headroom above the 100% bars for readable in-frame labels.
    # Leave a label band above the tallest bar so 100.0 remains inside the
    # axes frame after journal rasterization.
    ax2.set_ylim(0, 112)
    ax2.set_yticks(np.arange(0, 101, 20))
    ax2.set_ylabel("Planner + AC replay success (%)")
    ax2.set_title("2013 fixed-offer evaluation")
    for x, y in zip(positions, rates):
        ax2.text(x, min(y + 1.5, 110.0), f"{y:.1f}", ha="center", va="bottom", fontsize=8)
    fig.savefig(out_dir / "common_offer_temporal_evaluation.png", dpi=240)
    fig.savefig(out_dir / "common_offer_temporal_evaluation.pdf")
    plt.close(fig)


def run(
    primary: Path = ROOT / "results/location_sensitivity_external_2012_2013_strict_v4",
    source: Path = ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz",
    out_dir: Path = ROOT / "results/common_offer_temporal_evaluation_strict_v6",
    sites: tuple[str, ...] = SITES,
) -> pd.DataFrame:
    policy = pd.read_csv(primary / "policy_rows.csv")
    policy["site"] = policy["site"].astype(str)
    network = policy[(policy.method == "network_lp") & (policy.site.isin(sites))].copy()
    network["year"] = network["date"].astype(str).str[:4]
    calibration = network[(network.year == CALIBRATION_YEAR) & (network.baseline_feasible.astype(int) == 1)]
    if calibration.empty:
        raise ValueError("no baseline-feasible calibration rows")
    calibration_key = ["date", "group", "site"]
    if calibration.duplicated(calibration_key).any():
        raise ValueError("duplicate calibration date/group/site units")
    offer = float(np.quantile(calibration.service_kw.to_numpy(float), 1.0 - TARGET_COVERAGE, method="linear"))

    bounds = _bounds_lookup(primary / "ac_bounds.csv")
    bank = load_bank(exp.BANK_PATH)
    load, pv, dates = _embedded_external(bank, source)
    date_year = pd.Series(dates.astype(str)).str[:4].to_numpy()
    evaluation = network[(network.year == EVALUATION_YEAR) & (network.baseline_feasible.astype(int) == 1)].copy()
    if evaluation.empty:
        raise ValueError("no baseline-feasible evaluation rows")
    if evaluation.duplicated(calibration_key).any():
        raise ValueError("duplicate evaluation date/group/site units")

    out_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "status": "common_offer_temporal_evaluation_strict_v6",
        "sites": list(sites),
        "calibration_year": CALIBRATION_YEAR,
        "evaluation_year": EVALUATION_YEAR,
        "calibration_rule": "pooled lower (1-target_empirical_coverage) quantile of network_lp service_kw over baseline-AC-feasible units at all seven sites; np.quantile(method=linear)",
        "target_empirical_coverage": TARGET_COVERAGE,
        "common_offer_kw": offer,
        "calibration_units": int(len(calibration)),
        "evaluation_units_before_replay": int(len(evaluation)),
        "source": str(source.relative_to(ROOT)),
        "source_sha256": _source_sha256(source),
        "processed_metadata": "data/processed/ausgrid_external_2012_2013_strict.json",
        "processed_metadata_sha256": _source_sha256(ROOT / "data/processed/ausgrid_external_2012_2013_strict.json"),
        "retained_dates_total": int(len(dates)),
        "calibration_dates": int(np.sum(date_year == CALIBRATION_YEAR)),
        "evaluation_dates": int(np.sum(date_year == EVALUATION_YEAR)),
        "calibration_date_list": sorted(set(dates[date_year == CALIBRATION_YEAR].astype(str))),
        "evaluation_date_list": sorted(set(dates[date_year == EVALUATION_YEAR].astype(str))),
        "seed": BOOT_SEED,
        "n_boot": N_BOOT,
        "script": "scripts/build_common_offer_temporal_evaluation.py",
        "script_sha256": _source_sha256(Path(__file__)),
        "calibration_unit_key_unique": True,
        "evaluation_unit_key_unique": True,
        "ac_replay": "plan_service at common offer followed by interval nonlinear OpenDSS replay; no site-specific retuning",
        "shortfall_definition": "max(common_offer_kw - local network-LP frontier endpoint, 0) multiplied by four service hours; scalar-frontier diagnostic, not AC replay unmet energy",
        "claim_boundary": "temporal screening experiment over the retained 2012/2013 blocks, not a probabilistic future delivery guarantee",
    }
    (out_dir / "threshold_metadata.json").write_text(json.dumps(metadata, indent=2))

    all_rows = []
    for site in sites:
        site_eval = evaluation[evaluation.site == str(site)].copy()
        if site_eval.empty:
            raise ValueError(f"no evaluation rows for site {site}")
        result = _fixed_rows(str(site), offer, site_eval, bounds, load, pv, dates)
        all_rows.append(result)
        result.to_csv(out_dir / f"rows_{str(site).replace('.', '_')}.csv", index=False)
    rows = pd.concat(all_rows, ignore_index=True)
    rows.to_csv(out_dir / "rows.csv", index=False)
    rows[(rows.planner_feasible == 0) | (rows.replay_feasible == 0)].to_csv(
        out_dir / "failure_records.csv", index=False
    )

    summary_rows = []
    site_stats: dict[str, dict[str, object]] = {}
    for site, g in rows.groupby("site", sort=True):
        site_stat = _interval_summary(g, context=f"site_{site}_evaluation")
        site_stats[str(site)] = site_stat
        summary_rows.append({
            "site": site,
            "n_units": int(len(g)),
            "n_dates": int(g.date.nunique()),
            "planner_rate": float(g.planner_feasible.mean()),
            "replay_rate_conditional_planner": float(g.loc[g.planner_feasible == 1, "replay_feasible"].mean()) if (g.planner_feasible == 1).any() else float("nan"),
            "joint_replay_rate": float((g.planner_feasible.astype(int) & g.replay_feasible.astype(int)).mean()),
            "mean_shortfall_kwh": float(g.shortfall_kwh.mean()),
            "joint_ci_low": float(site_stat["success"]["ci_low"]),
            "joint_ci_high": float(site_stat["success"]["ci_high"]),
            "planner_ci_low": float(site_stat["planner_success"]["ci_low"]),
            "planner_ci_high": float(site_stat["planner_success"]["ci_high"]),
        })
    site_summary = pd.DataFrame(summary_rows)
    site_summary.to_csv(out_dir / "site_summary.csv", index=False)

    pooled_eval = _interval_summary(rows[rows.year == EVALUATION_YEAR], context="pooled_evaluation")
    payload = {
        "metadata": metadata,
        "canonical_context": "pooled_evaluation",
        "pooled_evaluation": pooled_eval,
        "sites": [site_stats[str(site)] for site in sorted(site_stats)],
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2))

    date_summary = rows.groupby(["date", "year"], sort=True).agg(
        joint_replay_rate=("replay_feasible", "mean"),
        planner_rate=("planner_feasible", "mean"),
        mean_shortfall_kwh=("shortfall_kwh", "mean"),
        n_units=("replay_feasible", "size"),
    ).reset_index()
    date_summary.to_csv(out_dir / "date_summary.csv", index=False)

    _plot_evaluation(network, site_summary, offer, out_dir, sites)
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, default=ROOT / "results/location_sensitivity_external_2012_2013_strict_v4")
    parser.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/common_offer_temporal_evaluation_strict_v6")
    parser.add_argument("--sites", nargs="+", default=list(SITES))
    args = parser.parse_args()
    result = run(args.primary, args.source, args.out_dir, tuple(args.sites))
    print(result.groupby("site")["replay_feasible"].mean().to_string())
