#!/usr/bin/env python3
"""Run a pre-frozen three-call contract grid under audited scalar AC bounds.

The v5 two-call endpoint is export-floor dominated at 2 MWh and its finite
information contrast is confounded by hiding the terminal target.  This
additive experiment keeps the terminal SOC target visible, adds a third
service call, and tests whether a middle recovery interval creates a
chronological delivery contraction that survives aggregate energy relaxations.

The second call starts at 14, 16, 20, or 24; the calls are
``[8,12)``, ``[s,s+4)``, and ``[32,36)``.  Recovery is allowed only in
``[12,s)``, ``[s+4,32)``, and ``[36,48)``.  Every cell is evaluated for both
primary placements, every baseline-gated date/group unit, and four declared
capacities.  The script writes scalar-bound results only; selected cells can
later be replayed through OpenDSS by a separate, explicitly frozen audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from recoveryflex.capacity_certificate import capacity_certificate  # noqa: E402
from recoveryflex.dispatch import plan_service  # noqa: E402

FIRST = (8, 12)
SECOND_STARTS = (14, 16, 20, 24)
THIRD = (32, 36)
CAPACITIES_KWH = (250.0, 500.0, 1000.0, 2000.0)
SITES = ("611.3", "634.1")
DT_H = 0.5
ETA_C = 0.95
ETA_D = 0.95
INITIAL_SOC = 0.80
TERMINAL_SOC = 0.80
SOC_MIN = 0.20
SOC_MAX = 1.00
N_BOOT = 5000
BOOT_SEED = 20261003
TOL_KW = 1e-7
ESTIMAND_VERSION = "date-vs-unit-weighted-v1"

DEFAULT_BOUNDS = ROOT / "results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv"
DEFAULT_POLICY = ROOT / "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv"
DEFAULT_OUT = ROOT / "results/three_call_grid_v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def protocol_spec() -> dict[str, object]:
    """Return the complete frozen contract specification used by this run.

    Keeping this object in the result metadata makes the protocol hash
    independent of source-file paths and of the order in which JSON keys are
    written.  The same canonical object is what a reviewer can use to verify
    that a replay belongs to this grid rather than to a post-hoc variant.
    """
    return {
        "service_windows": [list(FIRST), "[s,s+4)", list(THIRD)],
        "second_start_intervals": list(SECOND_STARTS),
        "recovery_windows": "[12,s), [s+4,32), [36,48)",
        "terminal_visibility": "always",
        "terminal_mode": "exact",
        "capacities_kwh": list(CAPACITIES_KWH),
        "initial_soc": INITIAL_SOC,
        "terminal_soc": TERMINAL_SOC,
        "soc_bounds": [SOC_MIN, SOC_MAX],
        "efficiencies": [ETA_C, ETA_D],
        "dt_h": DT_H,
        "sites": list(SITES),
    }


def protocol_sha256(spec: dict[str, object]) -> str:
    payload = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def contract(second_start: int) -> tuple[tuple[tuple[int, int], ...], tuple[tuple[int, int], ...]]:
    s = int(second_start)
    if s not in SECOND_STARTS:
        raise ValueError(f"second_start must be one of {SECOND_STARTS}")
    services = (FIRST, (s, s + 4), THIRD)
    recovery = ((12, s), (s + 4, 32), (36, 48))
    return services, recovery


def _cluster_bootstrap(frame: pd.DataFrame, value: str, context: tuple[Any, ...]) -> dict[str, float | int]:
    """Return the date-weighted mean and its date-cluster bootstrap interval.

    The row-level table has one row per date--group--site unit.  A plain
    ``frame[value].mean()`` is therefore a unit-weighted estimand, whereas the
    bootstrap below first averages within date and then averages dates.  Both
    estimands are retained in the summary so headline values cannot silently
    mix them (the retained calendar has equal group counts in the current
    protocol, but that equality is a data property rather than a definition).
    """
    grouped = frame[["date", value]].groupby("date", sort=True, as_index=False)[value].mean()
    means = grouped[value].to_numpy(float)
    if means.size == 0:
        return {
            "estimate": float("nan"), "ci_low": float("nan"),
            "ci_high": float("nan"), "n_dates": 0,
            "n_units": 0, "unit_weighted_estimate": float("nan"),
        }
    estimate = float(means.mean())
    if means.size == 1:
        draws = np.array([estimate])
    else:
        payload = repr((BOOT_SEED, tuple(str(x) for x in context))).encode("utf-8")
        seed = int.from_bytes(hashlib.sha256(payload).digest()[:16], "little", signed=False)
        rng = np.random.default_rng(seed)
        draws = means[rng.integers(0, means.size, size=(N_BOOT, means.size))].mean(axis=1)
    return {
        "estimate": estimate,
        "ci_low": float(np.quantile(draws, 0.025)),
        "ci_high": float(np.quantile(draws, 0.975)),
        "n_dates": int(means.size),
        "n_units": int(len(frame)),
        "unit_weighted_estimate": float(frame[value].mean()),
    }


def _greedy_feasible(p: float, charge: np.ndarray, export: np.ndarray, E: float, services: tuple[tuple[int, int], ...], recovery: tuple[tuple[int, int], ...]) -> bool:
    service = np.zeros(48, dtype=bool)
    for a, b in services:
        service[a:b] = True
    rec = np.zeros(48, dtype=bool)
    for a, b in recovery:
        rec[a:b] = True
    energy = E * INITIAL_SOC
    lo, hi = E * SOC_MIN, E * SOC_MAX
    for t in range(48):
        if service[t]:
            if p > export[t] + 1e-8:
                return False
            energy -= p * DT_H / ETA_D
        elif rec[t]:
            q = min(charge[t], max(0.0, (hi - energy) / (ETA_C * DT_H)))
            energy += ETA_C * q * DT_H
        if energy < lo - 1e-7 or energy > hi + 1e-7:
            return False
    return energy >= E * TERMINAL_SOC - 1e-7


def _greedy_endpoint(charge: np.ndarray, export: np.ndarray, E: float, services: tuple[tuple[int, int], ...], recovery: tuple[tuple[int, int], ...]) -> float:
    service_indices = [t for a, b in services for t in range(a, b)]
    lo, hi = 0.0, float(np.min(export[service_indices]))
    if not _greedy_feasible(0.0, charge, export, E, services, recovery):
        return 0.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if _greedy_feasible(mid, charge, export, E, services, recovery):
            lo = mid
        else:
            hi = mid
    return float(lo)


def _relaxed_bound(charge: np.ndarray, export: np.ndarray, E: float, services: tuple[tuple[int, int], ...], recovery: tuple[tuple[int, int], ...]) -> tuple[float, float, float, float, list[float]]:
    service_indices = [t for a, b in services for t in range(a, b)]
    service_hours = sum(b - a for a, b in services) * DT_H
    first_hours = (services[0][1] - services[0][0]) * DT_H
    b_svc = float(np.min(export[service_indices]))
    first = float(E * (INITIAL_SOC - SOC_MIN) * ETA_D / first_hours)
    recovery_all = [t for a, b in recovery for t in range(a, b)]
    total = float(ETA_D * np.sum(ETA_C * charge[recovery_all] * DT_H) / service_hours)
    prefix: list[float] = []
    # Necessary aggregate bounds at the start of calls 2 and 3.  They count
    # all service energy through the call and all recovery headroom before it,
    # while ignoring chronological placement within those recovery intervals.
    for k, (start, _end) in enumerate(services[1:], start=2):
        before = [t for a, b in recovery for t in range(a, b) if t < start]
        energy = E * (INITIAL_SOC - SOC_MIN) + np.sum(ETA_C * charge[before] * DT_H)
        prefix.append(float(ETA_D * energy / (k * 2.0)))
    return float(min([b_svc, first, total, *prefix])), b_svc, first, total, prefix


def _read_inputs(bounds_path: Path, policy_path: Path) -> tuple[pd.DataFrame, dict[tuple[str, int, int, str], tuple[np.ndarray, np.ndarray]]]:
    bounds = pd.read_csv(bounds_path)
    bounds["date"] = bounds.date.astype(str)
    bounds["site"] = bounds.site.astype(str)
    bound_map: dict[tuple[str, int, int, str], tuple[np.ndarray, np.ndarray]] = {}
    for key, group in bounds.groupby(["date", "day_index", "group", "site"], sort=False):
        group = group.sort_values("interval")
        if len(group) != 48 or not np.array_equal(group.interval.to_numpy(), np.arange(48)):
            raise ValueError(f"expected 48 ordered rows for {key}")
        bound_map[(str(key[0]), int(key[1]), int(key[2]), str(key[3]))] = (group.charge_limit_kw.to_numpy(float), group.export_limit_kw.to_numpy(float))
    policy = pd.read_csv(policy_path)
    policy["date"] = policy.date.astype(str)
    policy["site"] = policy.site.astype(str)
    policy = policy[(policy.method == "network_lp") & (policy.baseline_feasible.astype(int) == 1) & policy.site.isin(SITES)].copy()
    policy = policy.drop_duplicates(["date", "day_index", "group", "site"])
    return policy.sort_values(["site", "date", "group", "day_index"]).reset_index(drop=True), bound_map


def run(bounds_path: Path, policy_path: Path, out_dir: Path) -> dict[str, object]:
    policy, bound_map = _read_inputs(bounds_path, policy_path)
    rows: list[dict[str, object]] = []
    for r in policy.itertuples(index=False):
        key = (str(r.date), int(r.day_index), int(r.group), str(r.site))
        charge, export = bound_map[key]
        for E in CAPACITIES_KWH:
            for s in SECOND_STARTS:
                services, recovery = contract(s)
                relaxed, b_svc, first, total, prefix = _relaxed_bound(charge, export, E, services, recovery)
                lp = plan_service(charge, export, np.zeros(48), services, recovery_windows=recovery, energy_kwh=E, initial_soc=INITIAL_SOC, terminal_soc_target=TERMINAL_SOC, soc_min=SOC_MIN, soc_max=SOC_MAX, eta_charge=ETA_C, eta_discharge=ETA_D, dt_h=DT_H, terminal_mode="exact", mode="network_lp")
                p_lp = float(lp.service_kw) if lp.feasible else 0.0
                fixed_ratio = sum(b - a for a, b in services) / (sum(b - a for a, b in recovery) * ETA_C * ETA_D)
                fixed = plan_service(charge, export, np.zeros(48), services, recovery_windows=recovery, energy_kwh=E, initial_soc=INITIAL_SOC, terminal_soc_target=TERMINAL_SOC, soc_min=SOC_MIN, soc_max=SOC_MAX, eta_charge=ETA_C, eta_discharge=ETA_D, dt_h=DT_H, terminal_mode="exact", mode="fixed_recovery", fixed_recovery_ratio=fixed_ratio)
                p_fixed = float(fixed.service_kw) if fixed.feasible else 0.0
                p_greedy = _greedy_endpoint(charge, export, E, services, recovery)
                certificate = capacity_certificate(relaxed, charge, export, services, recovery, energy_efficiency_charge=ETA_C, energy_efficiency_discharge=ETA_D, dt_h=DT_H, initial_soc=INITIAL_SOC, terminal_soc_target=TERMINAL_SOC, soc_min=SOC_MIN, soc_max=SOC_MAX, terminal_mode="exact")
                cert_at_E = bool(certificate.feasible and certificate.e_min_kwh <= E + 1e-7 and E <= certificate.e_max_kwh + 1e-7)
                witness = certificate.lower_witness if E < certificate.e_min_kwh else certificate.upper_witness
                rows.append({
                    "date": str(r.date), "day_index": int(r.day_index), "group": int(r.group), "site": str(r.site), "capacity_kwh": float(E), "second_start": int(s), "second_gap_h": float((s - 12) * DT_H),
                    "service_power_lp_kw": p_lp, "service_power_greedy_kw": p_greedy, "service_power_fixed_ratio_kw": p_fixed, "fixed_ratio": float(fixed_ratio), "relaxed_bound_kw": relaxed, "service_floor_kw": b_svc, "first_call_bound_kw": first, "total_recovery_bound_kw": total, "prefix_call2_bound_kw": prefix[0], "prefix_call3_bound_kw": prefix[1], "chronology_contraction_kw": max(0.0, relaxed - p_lp), "lp_minus_greedy_kw": p_lp - p_greedy, "lp_minus_fixed_kw": p_lp - p_fixed, "greedy_match": int(abs(p_lp - p_greedy) <= 1e-5), "certificate_feasible_at_relaxed_bound": int(cert_at_E), "certificate_e_min_kwh": float(certificate.e_min_kwh), "certificate_e_max_kwh": float(certificate.e_max_kwh), "certificate_witness_kind": witness.kind if witness else "", "certificate_witness_start": witness.start if witness else -1, "certificate_witness_end": witness.end if witness else -1, "certificate_message": certificate.message,
                })
    detail = pd.DataFrame(rows)
    summaries: list[dict[str, object]] = []
    for (site, E, s), group in detail.groupby(["site", "capacity_kwh", "second_start"], sort=True):
        gap = _cluster_bootstrap(group, "chronology_contraction_kw", (site, E, s, "gap"))
        lp = _cluster_bootstrap(group, "service_power_lp_kw", (site, E, s, "lp"))
        fixed = _cluster_bootstrap(group, "lp_minus_fixed_kw", (site, E, s, "fixed"))
        relaxed = _cluster_bootstrap(group, "relaxed_bound_kw", (site, E, s, "relaxed"))
        witnesses = group.loc[group.chronology_contraction_kw > TOL_KW, "certificate_witness_kind"]
        summaries.append({
            "site": site, "capacity_kwh": float(E), "second_start": int(s),
            "second_gap_h": float((int(s) - 12) * DT_H), "n_units": int(len(group)),
            "n_dates": int(group.date.nunique()),
            # All *_mean_kw headline fields are date-weighted means (mean of
            # date means), with date-cluster CIs.  Explicit *_unit_mean_kw
            # fields prevent accidental mixing with pooled row means.
            "estimand": "date_weighted_mean_of_date_means",
            "lp_mean_kw": lp["estimate"], "lp_ci_low_kw": lp["ci_low"],
            "lp_ci_high_kw": lp["ci_high"],
            "lp_unit_mean_kw": lp["unit_weighted_estimate"],
            "relaxed_bound_mean_kw": relaxed["estimate"],
            "relaxed_bound_unit_mean_kw": relaxed["unit_weighted_estimate"],
            "contraction_mean_kw": gap["estimate"],
            "contraction_ci_low_kw": gap["ci_low"],
            "contraction_ci_high_kw": gap["ci_high"],
            "contraction_unit_mean_kw": gap["unit_weighted_estimate"],
            "contraction_fraction": float((group.chronology_contraction_kw > TOL_KW).mean()),
            "fixed_lp_gap_mean_kw": fixed["estimate"],
            "fixed_lp_gap_unit_mean_kw": fixed["unit_weighted_estimate"],
            "greedy_match_fraction": float(group.greedy_match.mean()),
            "certificate_witness_counts": json.dumps({str(k): int(v) for k, v in witnesses.value_counts().items()}, sort_keys=True),
        })
    summary = pd.DataFrame(summaries).sort_values(["site", "capacity_kwh", "second_start"])
    out_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(out_dir / "three_call_rows.csv", index=False)
    summary.to_csv(out_dir / "three_call_summary.csv", index=False)
    spec = protocol_spec()
    main_cell = detail[(detail.site == "634.1") & (detail.capacity_kwh == 500.0) & (detail.second_start == 24)]
    # Reuse the same bootstrap contexts as the summary row so the metadata
    # cannot expose a second CI for the same headline cell.
    main_gap = _cluster_bootstrap(main_cell, "chronology_contraction_kw", ("634.1", 500.0, 24, "gap")) if len(main_cell) else {}
    main_lp = _cluster_bootstrap(main_cell, "service_power_lp_kw", ("634.1", 500.0, 24, "lp")) if len(main_cell) else {}
    main_relaxed = _cluster_bootstrap(main_cell, "relaxed_bound_kw", ("634.1", 500.0, 24, "relaxed")) if len(main_cell) else {}
    metadata = {
        "status": "three_call_grid_v1", "question": "Does a third call create a chronological recovery-window contraction after aggregate service-floor, initial-SOC, prefix, and total-recovery relaxations?", "contract": spec, "protocol_sha256": protocol_sha256(spec),
        "population": {"sites": list(SITES), "baseline_gated_units": int(len(policy)), "dates": int(policy.date.nunique()), "groups": int(policy.group.nunique())},
        "estimand_version": ESTIMAND_VERSION,
        "estimands": {
            "primary": "date-weighted mean of date means of aggregate relaxed bound minus exact scalar LP endpoint (reported as a non-negative numerical-tolerance-clipped gap)",
            "primary_raw": "relaxed_bound_kw - service_power_lp_kw",
            "unit_weighted_secondary": "pooled mean over date--group--site rows; retained in *_unit_mean_kw fields and never mixed with primary CIs",
            "date_weighted_definition": "For each site/capacity/start cell, average rows within each retained date, then average the 219 date means with equal date weights",
            "aggregate_relaxation": "minimum of service floor, first-call SOC, total recovery, and cumulative prefix bounds at calls 2 and 3",
            "contraction_clip": "max(0, raw gap); values below 1e-7 kW are numerical zero",
            "uncertainty": "date-cluster bootstrap over date means, 5000 replicates, seed 20261003",
        },
        "main_cell_estimands": {
            "site": "634.1", "capacity_kwh": 500.0, "second_start": 24,
            "n_units": int(len(main_cell)), "n_dates": int(main_cell.date.nunique()),
            "date_weighted": {"relaxed_bound_kw": main_relaxed.get("estimate"), "service_power_lp_kw": main_lp.get("estimate"), "contraction_kw": main_gap.get("estimate"), "ci_low_kw": main_gap.get("ci_low"), "ci_high_kw": main_gap.get("ci_high")},
            "unit_weighted": {"relaxed_bound_kw": main_relaxed.get("unit_weighted_estimate"), "service_power_lp_kw": main_lp.get("unit_weighted_estimate"), "contraction_kw": main_gap.get("unit_weighted_estimate")},
            "warning": "Do not subtract a date-weighted bound from a unit-weighted endpoint; that mixing produced the historical 4.275-vs-4.288 discrepancy.",
        },
        "source_hashes": {"bounds": sha256(bounds_path), "policy": sha256(policy_path)}, "files": ["three_call_rows.csv", "three_call_summary.csv", "metadata.json"], "limitations": ["scalar dispatch under frozen audited AC bounds", "no OpenDSS replay in this grid", "single IEEE-13 feeder and two primary placements"]
    }
    metadata["script_sha256"] = sha256(Path(__file__).resolve())
    metadata["python_runtime"] = sys.version.split()[0]
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"summary_rows": int(len(summary)), "detail_rows": int(len(detail)), "metadata": metadata}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bounds", type=Path, default=DEFAULT_BOUNDS)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.bounds, args.policy, args.out_dir), indent=2))
