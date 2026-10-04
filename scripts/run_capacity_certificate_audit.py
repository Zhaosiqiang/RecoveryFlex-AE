#!/usr/bin/env python3
"""Audit the exact scalar-SOC capacity certificate against ``plan_service``.

This is a supplementary audit.  It reads the frozen AC-bound and policy
tables, computes the cumulative-window certificate for a fixed service power,
and then probes the existing HiGHS LP just below/above the certified capacity
boundary.  It does not regenerate or overwrite any v5 result table.
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

from recoveryflex.capacity_certificate import CapacityCertificate, capacity_certificate
from recoveryflex.dispatch import plan_service

SERVICE_WINDOWS = ((8, 12), (24, 28))
RECOVERY_WINDOWS = ((12, 24), (28, 48))
ETA_CHARGE = 0.95
ETA_DISCHARGE = 0.95
DT_H = 0.5
INITIAL_SOC = 0.80
TERMINAL_SOC = 0.80
SOC_MIN = 0.20
SOC_MAX = 1.00
REFERENCE_CAPACITY_KWH = 2000.0


def _unit_key(row: pd.Series) -> tuple[str, int, int, str]:
    return (str(row.date), int(row.group), int(row.day_index), str(row.site))


def _select_units(policy: pd.DataFrame, sites: tuple[str, ...], max_units: int) -> pd.DataFrame:
    frame = policy[(policy.method == "network_lp") & (policy.baseline_feasible == 1)].copy()
    frame["site"] = frame["site"].astype(str)
    frame = frame[frame.site.isin(sites)].sort_values(["site", "date", "group", "day_index"])
    frame = frame.drop_duplicates(["date", "day_index", "group", "site"])
    if max_units <= 0:
        return frame.reset_index(drop=True)
    per_site = max(1, max_units // max(1, len(sites)))
    chunks = [g.head(per_site) for _, g in frame.groupby("site", sort=True)]
    selected = pd.concat(chunks, ignore_index=True) if chunks else frame.head(0)
    # Keep the most demanding unit at each site in a small audit even when it
    # falls outside the chronological head of the table.
    for site, group in frame.groupby("site", sort=True):
        if group.empty:
            continue
        selected = pd.concat([selected, group.loc[[group.service_kw.idxmax()]]], ignore_index=True)
    return selected.drop_duplicates(["date", "day_index", "group", "site"]).reset_index(drop=True)


def _common_lp_kwargs(charge: np.ndarray, export: np.ndarray, P: float, E: float) -> dict[str, object]:
    return dict(
        charge_limit_kw=charge,
        export_limit_kw=export,
        load_kw=np.zeros(charge.size, dtype=float),
        service_windows=SERVICE_WINDOWS,
        recovery_windows=RECOVERY_WINDOWS,
        energy_kwh=float(E),
        initial_soc=INITIAL_SOC,
        terminal_soc_target=TERMINAL_SOC,
        soc_min=SOC_MIN,
        soc_max=SOC_MAX,
        eta_charge=ETA_CHARGE,
        eta_discharge=ETA_DISCHARGE,
        dt_h=DT_H,
        mode="network_lp",
        service_power_kw=float(P),
        terminal_mode="exact",
    )


def _probe_capacities(cert: CapacityCertificate) -> list[tuple[str, float, bool]]:
    e_min = cert.e_min_kwh
    probes: list[tuple[str, float, bool]] = []
    if cert.feasible and np.isfinite(e_min) and e_min > 1e-8:
        probes.append(("below_e_min", max(1e-6, e_min * (1.0 - 1e-5)), False))
        probes.append(("above_e_min", e_min * (1.0 + 1e-5), True))
    else:
        probes.append(("positive_capacity", 1.0, cert.feasible))
    if cert.feasible:
        probes.append(("reference_2000", REFERENCE_CAPACITY_KWH, True))
        if np.isfinite(cert.e_max_kwh) and cert.e_max_kwh > e_min + 1e-7:
            probes.append(("above_e_max", cert.e_max_kwh * (1.0 + 1e-5), False))
    return probes


def run(
    bounds_path: Path,
    policy_path: Path,
    out_dir: Path,
    sites: tuple[str, ...],
    max_units: int,
) -> dict[str, object]:
    bounds = pd.read_csv(bounds_path)
    bounds["site"] = bounds["site"].astype(str)
    policy = pd.read_csv(policy_path)
    selected = _select_units(policy, sites, max_units)
    rows: list[dict[str, object]] = []
    lp_rows: list[dict[str, object]] = []
    for _, policy_row in selected.iterrows():
        date = str(policy_row.date)
        day_index = int(policy_row.day_index)
        group = int(policy_row.group)
        site = str(policy_row.site)
        subset = bounds[
            (bounds.date.astype(str) == date)
            & (bounds.day_index == day_index)
            & (bounds.group == group)
            & (bounds.site == site)
        ].sort_values("interval")
        if len(subset) != 48:
            raise ValueError(f"expected 48 AC-bound rows for {(date, day_index, group, site)}, got {len(subset)}")
        charge = subset.charge_limit_kw.to_numpy(float)
        export = subset.export_limit_kw.to_numpy(float)
        P = float(policy_row.service_kw)
        cert = capacity_certificate(
            P,
            charge,
            export,
            SERVICE_WINDOWS,
            RECOVERY_WINDOWS,
            energy_efficiency_charge=ETA_CHARGE,
            energy_efficiency_discharge=ETA_DISCHARGE,
            dt_h=DT_H,
            initial_soc=INITIAL_SOC,
            terminal_soc_target=TERMINAL_SOC,
            soc_min=SOC_MIN,
            soc_max=SOC_MAX,
            terminal_mode="exact",
        )
        row = {
            "date": date,
            "day_index": day_index,
            "group": group,
            "site": site,
            "service_kw": P,
            "certificate_feasible": int(cert.feasible),
            "e_min_kwh": cert.e_min_kwh,
            "e_max_kwh": cert.e_max_kwh,
            "cuts_checked": cert.cuts_checked,
            "message": cert.message,
        }
        if cert.lower_witness:
            row.update({
                "lower_kind": cert.lower_witness.kind,
                "lower_start": cert.lower_witness.start,
                "lower_end": cert.lower_witness.end,
                "lower_left_coefficient": cert.lower_witness.left_coefficient,
                "lower_right_constant": cert.lower_witness.right_constant,
                "lower_charge_kwh": cert.lower_witness.charge_kwh,
                "lower_discharge_kwh": cert.lower_witness.discharge_kwh,
                "lower_residual_at_boundary": cert.lower_witness.residual,
            })
        if cert.upper_witness:
            row.update({
                "upper_kind": cert.upper_witness.kind,
                "upper_start": cert.upper_witness.start,
                "upper_end": cert.upper_witness.end,
                "upper_left_coefficient": cert.upper_witness.left_coefficient,
                "upper_right_constant": cert.upper_witness.right_constant,
                "upper_charge_kwh": cert.upper_witness.charge_kwh,
                "upper_discharge_kwh": cert.upper_witness.discharge_kwh,
                "upper_residual_at_boundary": cert.upper_witness.residual,
            })
        rows.append(row)
        for label, E, expected in _probe_capacities(cert):
            result = plan_service(**_common_lp_kwargs(charge, export, P, E))
            observed = bool(result.feasible)
            lp_rows.append({
                "date": date,
                "day_index": day_index,
                "group": group,
                "site": site,
                "service_kw": P,
                "probe": label,
                "capacity_kwh": E,
                "expected_feasible": int(expected),
                "lp_feasible": int(observed),
                "match": int(observed == expected),
                "lp_message": result.message,
            })

    out_dir.mkdir(parents=True, exist_ok=True)
    cert_df = pd.DataFrame(rows)
    lp_df = pd.DataFrame(lp_rows)
    cert_df.to_csv(out_dir / "certificate_rows.csv", index=False)
    lp_df.to_csv(out_dir / "lp_crosscheck.csv", index=False)
    active_counts = (
        cert_df["lower_kind"].fillna("none").value_counts().to_dict() if not cert_df.empty else {}
    )
    summary = {
        "audit": "exact scalar-SOC cumulative-window capacity certificate",
        "protocol": "fixed service power from frozen network_lp endpoint; scalar bounds only; no OpenDSS rerun",
        "source_bounds": str(bounds_path),
        "source_policy": str(policy_path),
        "sites": list(sites),
        "max_units_argument": max_units,
        "units_selected": int(len(cert_df)),
        "certificate_feasible_count": int(cert_df.certificate_feasible.sum()) if not cert_df.empty else 0,
        "e_min_min_kwh": float(cert_df.e_min_kwh.min()) if not cert_df.empty else None,
        "e_min_median_kwh": float(cert_df.e_min_kwh.median()) if not cert_df.empty else None,
        "e_min_max_kwh": float(cert_df.e_min_kwh.max()) if not cert_df.empty else None,
        "active_lower_witness_counts": active_counts,
        "lp_probes": int(len(lp_df)),
        "lp_match_count": int(lp_df.match.sum()) if not lp_df.empty else 0,
        "lp_match_rate": float(lp_df.match.mean()) if not lp_df.empty else None,
        "parameters": {
            "service_windows": [list(x) for x in SERVICE_WINDOWS],
            "recovery_windows": [list(x) for x in RECOVERY_WINDOWS],
            "eta_charge": ETA_CHARGE,
            "eta_discharge": ETA_DISCHARGE,
            "dt_h": DT_H,
            "initial_soc": INITIAL_SOC,
            "terminal_soc_target": TERMINAL_SOC,
            "soc_min": SOC_MIN,
            "soc_max": SOC_MAX,
            "terminal_mode": "exact",
        },
        "files": ["certificate_rows.csv", "lp_crosscheck.csv", "summary.json"],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bounds", type=Path,
        default=ROOT / "results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv",
    )
    parser.add_argument(
        "--policy", type=Path,
        default=ROOT / "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv",
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/capacity_certificate_v1")
    parser.add_argument("--sites", nargs="+", default=["611.3", "634.1"])
    parser.add_argument("--max-units", type=int, default=24, help="units total; 0 audits all baseline-gated units")
    args = parser.parse_args()
    summary = run(args.bounds, args.policy, args.out_dir, tuple(str(x) for x in args.sites), args.max_units)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
