#!/usr/bin/env python3
"""Run a frozen service-interval/capacity grid for repeated-service delivery.

This experiment is deliberately additive to the v5 results.  It keeps the
first call fixed at ``[8,12)`` and moves the second four-interval call across
five declared start times.  The terminal SOC target is always known and every
recovery interval is declared explicitly, so any contraction below the
service-window/export and total-energy relaxation is a chronological
recovery-window result rather than an information-visibility artefact.

The primary output is a scalar-bound sensitivity table over both primary
placements, all baseline-gated external units, four capacities, and five
second-call positions.  It includes the exact LP endpoint, a work-conserving
earliest-charge feasibility baseline, a necessary relaxed bound, the exact
cumulative-window certificate at that relaxed bound, and active-witness
classes.  It does not overwrite v5 outputs or claim a nonlinear AC validation;
the supplied charge/export limits are the already audited OpenDSS bounds.
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


SERVICE_FIRST = (8, 12)
SECOND_STARTS = (14, 16, 20, 24, 32)
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

DEFAULT_BOUNDS = ROOT / "results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv"
DEFAULT_POLICY = ROOT / "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv"
DEFAULT_OUT = ROOT / "results/contract_gap_grid_v1"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def service_windows(second_start: int) -> tuple[tuple[int, int], tuple[int, int]]:
    s = int(second_start)
    if s not in SECOND_STARTS:
        raise ValueError(f"second start must be one of {SECOND_STARTS}, got {s}")
    return SERVICE_FIRST, (s, s + 4)


def recovery_windows(second_start: int) -> tuple[tuple[int, int], tuple[int, int]]:
    s = int(second_start)
    return (12, s), (s + 4, 48)


def _unit_key(frame: pd.DataFrame) -> pd.Series:
    return (
        frame["date"].astype(str)
        + "|"
        + frame["day_index"].astype(str)
        + "|"
        + frame["group"].astype(str)
        + "|"
        + frame["site"].astype(str)
    )


def _cluster_bootstrap(values: pd.DataFrame, value: str, context: tuple[Any, ...]) -> dict[str, float | int]:
    """Deterministic date-cluster bootstrap for one cell."""
    work = values[["date", value]].copy()
    work[value] = pd.to_numeric(work[value], errors="raise")
    grouped = work.groupby("date", sort=True, as_index=False)[value].mean()
    means = grouped[value].to_numpy(float)
    if means.size == 0:
        return {"estimate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "n_dates": 0}
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
    }


def _greedy_feasible(
    p: float,
    charge: np.ndarray,
    export: np.ndarray,
    E: float,
    services: tuple[tuple[int, int], tuple[int, int]],
    recovery: tuple[tuple[int, int], tuple[int, int]],
) -> bool:
    """Work-conserving earliest-charge feasibility for exact terminal SOC.

    Charging is maximized at each declared recovery interval.  Since charge
    can be continuously curtailed and the second call is followed by a
    recovery interval, the terminal target is reachable whenever the maximum
    trajectory reaches it and all intermediate lower/upper SOC constraints
    remain satisfied.  This is used only as a transparent comparator; the LP
    remains the primary endpoint.
    """
    n = charge.size
    service = np.zeros(n, dtype=bool)
    for a, b in services:
        service[a:b] = True
    rec = np.zeros(n, dtype=bool)
    for a, b in recovery:
        rec[a:b] = True
    energy = E * INITIAL_SOC
    lo, hi = E * SOC_MIN, E * SOC_MAX
    for t in range(n):
        if service[t]:
            if p > export[t] + 1e-8:
                return False
            energy -= p * DT_H / ETA_D
        elif rec[t]:
            charge_kw = min(charge[t], max(0.0, (hi - energy) / (ETA_C * DT_H)))
            energy += ETA_C * charge_kw * DT_H
        if energy < lo - 1e-7 or energy > hi + 1e-7:
            return False
    return energy >= E * TERMINAL_SOC - 1e-7


def _greedy_endpoint(
    charge: np.ndarray,
    export: np.ndarray,
    E: float,
    services: tuple[tuple[int, int], tuple[int, int]],
    recovery: tuple[tuple[int, int], tuple[int, int]],
) -> float:
    upper = float(min(export[t] for a, b in services for t in range(a, b)))
    lo, hi = 0.0, upper
    if not _greedy_feasible(lo, charge, export, E, services, recovery):
        return 0.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _greedy_feasible(mid, charge, export, E, services, recovery):
            lo = mid
        else:
            hi = mid
    return float(lo)


def _relaxed_bound(
    charge: np.ndarray,
    export: np.ndarray,
    E: float,
    services: tuple[tuple[int, int], tuple[int, int]],
    recovery: tuple[tuple[int, int], tuple[int, int]],
) -> tuple[float, float, float, float]:
    service_intervals = [t for a, b in services for t in range(a, b)]
    recovery_intervals = [t for a, b in recovery for t in range(a, b)]
    service_hours = sum(b - a for a, b in services) * DT_H
    first_hours = (services[0][1] - services[0][0]) * DT_H
    b_svc = float(np.min(export[service_intervals]))
    first_support = float(E * (INITIAL_SOC - SOC_MIN) * ETA_D / first_hours)
    total_recovery = float(
        ETA_D * np.sum(ETA_C * charge[recovery_intervals] * DT_H) / service_hours
    )
    return float(min(b_svc, first_support, total_recovery)), b_svc, first_support, total_recovery


def _read_inputs(bounds_path: Path, policy_path: Path) -> tuple[pd.DataFrame, dict[tuple[str, int, int, str], tuple[np.ndarray, np.ndarray]]]:
    bounds = pd.read_csv(bounds_path)
    bounds["site"] = bounds["site"].astype(str)
    bounds["date"] = bounds["date"].astype(str)
    bounds["interval"] = bounds["interval"].astype(int)
    required = {"date", "day_index", "group", "site", "interval", "charge_limit_kw", "export_limit_kw"}
    missing = sorted(required - set(bounds.columns))
    if missing:
        raise ValueError(f"bounds missing columns: {missing}")
    bound_map: dict[tuple[str, int, int, str], tuple[np.ndarray, np.ndarray]] = {}
    for key, group in bounds.groupby(["date", "day_index", "group", "site"], sort=False):
        group = group.sort_values("interval")
        if len(group) != 48 or not np.array_equal(group.interval.to_numpy(), np.arange(48)):
            raise ValueError(f"expected 48 ordered bound rows for {key}")
        bound_map[(str(key[0]), int(key[1]), int(key[2]), str(key[3]))] = (
            group.charge_limit_kw.to_numpy(float), group.export_limit_kw.to_numpy(float)
        )
    policy = pd.read_csv(policy_path)
    policy["site"] = policy["site"].astype(str)
    policy["date"] = policy["date"].astype(str)
    policy = policy[(policy.method == "network_lp") & (policy.baseline_feasible.astype(int) == 1)]
    policy = policy[policy.site.isin(SITES)].copy()
    policy = policy.drop_duplicates(["date", "day_index", "group", "site"])
    policy["unit_key"] = _unit_key(policy)
    return policy.sort_values(["site", "date", "group", "day_index"]).reset_index(drop=True), bound_map


def run(bounds_path: Path, policy_path: Path, out_dir: Path) -> dict[str, object]:
    policy, bound_map = _read_inputs(bounds_path, policy_path)
    rows: list[dict[str, object]] = []
    for r in policy.itertuples(index=False):
        key = (str(r.date), int(r.day_index), int(r.group), str(r.site))
        charge, export = bound_map[key]
        for E in CAPACITIES_KWH:
            for s in SECOND_STARTS:
                services = service_windows(s)
                recovery = recovery_windows(s)
                p_relax, b_svc, first_support, total_recovery = _relaxed_bound(charge, export, E, services, recovery)
                result = plan_service(
                    charge_limit_kw=charge,
                    export_limit_kw=export,
                    load_kw=np.zeros(48),
                    service_windows=services,
                    recovery_windows=recovery,
                    energy_kwh=E,
                    initial_soc=INITIAL_SOC,
                    terminal_soc_target=TERMINAL_SOC,
                    soc_min=SOC_MIN,
                    soc_max=SOC_MAX,
                    eta_charge=ETA_C,
                    eta_discharge=ETA_D,
                    dt_h=DT_H,
                    terminal_mode="exact",
                    mode="network_lp",
                )
                p_lp = float(result.service_kw) if result.feasible else 0.0
                p_greedy = _greedy_endpoint(charge, export, E, services, recovery)
                certificate = capacity_certificate(
                    p_relax,
                    charge,
                    export,
                    services,
                    recovery,
                    energy_efficiency_charge=ETA_C,
                    energy_efficiency_discharge=ETA_D,
                    dt_h=DT_H,
                    initial_soc=INITIAL_SOC,
                    terminal_soc_target=TERMINAL_SOC,
                    soc_min=SOC_MIN,
                    soc_max=SOC_MAX,
                    terminal_mode="exact",
                )
                contraction = max(0.0, p_relax - p_lp)
                # ``capacity_certificate.feasible`` means that *some*
                # capacity lies in the returned interval.  The experiment
                # needs feasibility at the tested E, so check membership in
                # [e_min, e_max] explicitly and retain the corresponding
                # lower/upper witness when the relaxed bound is not feasible
                # at this capacity.
                cert_at_capacity = bool(
                    certificate.feasible
                    and certificate.e_min_kwh <= E + 1e-7
                    and E <= certificate.e_max_kwh + 1e-7
                )
                if not cert_at_capacity:
                    witness = certificate.lower_witness if E < certificate.e_min_kwh else certificate.upper_witness
                    witness_kind = witness.kind if witness else "capacity_interval_empty"
                    witness_start = witness.start if witness else -1
                    witness_end = witness.end if witness else -1
                else:
                    witness_kind, witness_start, witness_end = "", -1, -1
                row: dict[str, object] = {
                    "date": str(r.date), "day_index": int(r.day_index), "group": int(r.group), "site": str(r.site),
                    "capacity_kwh": float(E), "second_start": int(s), "second_gap_h": float((s - 12) * DT_H),
                    "service_power_lp_kw": p_lp, "service_power_greedy_kw": p_greedy,
                    "relaxed_bound_kw": p_relax, "service_floor_kw": b_svc,
                    "first_call_soc_bound_kw": first_support, "total_recovery_bound_kw": total_recovery,
                    "chronology_contraction_kw": contraction,
                    "lp_endpoint_feasible": int(result.feasible or p_lp > 0),
                    "greedy_lp_abs_gap_kw": float(abs(p_lp - p_greedy)),
                    "greedy_match": int(abs(p_lp - p_greedy) <= 1e-5),
                    "relax_certificate_feasible": int(cert_at_capacity),
                    "relax_certificate_e_min_kwh": float(certificate.e_min_kwh),
                    "relax_certificate_e_max_kwh": float(certificate.e_max_kwh),
                    "relax_certificate_witness_kind": witness_kind,
                    "relax_certificate_witness_start": witness_start,
                    "relax_certificate_witness_end": witness_end,
                    "relax_certificate_message": certificate.message,
                }
                rows.append(row)

    detail = pd.DataFrame(rows)
    summary_rows: list[dict[str, object]] = []
    for (site, E, s), group in detail.groupby(["site", "capacity_kwh", "second_start"], sort=True):
        boot_gap = _cluster_bootstrap(group, "chronology_contraction_kw", (site, E, s, "gap"))
        boot_lp = _cluster_bootstrap(group, "service_power_lp_kw", (site, E, s, "lp"))
        witnesses = group.loc[group.chronology_contraction_kw > TOL_KW, "relax_certificate_witness_kind"]
        summary_rows.append({
            "site": site, "capacity_kwh": float(E), "second_start": int(s), "second_gap_h": float((int(s) - 12) * DT_H),
            "n_units": int(len(group)), "n_dates": int(group.date.nunique()),
            "lp_mean_kw": boot_lp["estimate"], "lp_ci_low_kw": boot_lp["ci_low"], "lp_ci_high_kw": boot_lp["ci_high"],
            "relaxed_bound_mean_kw": float(group.relaxed_bound_kw.mean()),
            "contraction_mean_kw": boot_gap["estimate"], "contraction_ci_low_kw": boot_gap["ci_low"], "contraction_ci_high_kw": boot_gap["ci_high"],
            "contraction_units": int((group.chronology_contraction_kw > TOL_KW).sum()),
            "contraction_fraction": float((group.chronology_contraction_kw > TOL_KW).mean()),
            "certificate_infeasible_fraction": float((group.relax_certificate_feasible == 0).mean()),
            "greedy_match_fraction": float(group.greedy_match.mean()),
            "greedy_max_abs_gap_kw": float(group.greedy_lp_abs_gap_kw.max()),
            "witness_counts": json.dumps({str(k): int(v) for k, v in witnesses.value_counts().items()}, sort_keys=True),
        })
    summary = pd.DataFrame(summary_rows).sort_values(["site", "capacity_kwh", "second_start"])
    out_dir.mkdir(parents=True, exist_ok=True)
    detail.to_csv(out_dir / "contract_gap_rows.csv", index=False)
    summary.to_csv(out_dir / "contract_gap_summary.csv", index=False)
    metadata = {
        "status": "contract_gap_grid_v1",
        "question": "Does moving the second service call create a chronology-limited delivery contraction when terminal SOC is always visible?",
        "contract": {
            "first_service_window": list(SERVICE_FIRST), "second_start_intervals": list(SECOND_STARTS),
            "second_service_length_intervals": 4, "recovery_windows": "(12,s) and (s+4,48)",
            "capacities_kwh": list(CAPACITIES_KWH), "initial_soc": INITIAL_SOC, "terminal_soc": TERMINAL_SOC,
            "soc_min": SOC_MIN, "soc_max": SOC_MAX, "eta_charge": ETA_C, "eta_discharge": ETA_D, "dt_h": DT_H,
            "terminal_visibility": "always", "endpoint_selection": "full-horizon scalar LP; no forecast uncertainty",
        },
        "population": {"sites": list(SITES), "baseline_gated_units": int(len(policy)), "dates": int(policy.date.nunique()), "groups": int(policy.group.nunique())},
        "estimands": {"relaxed_bound": "min(service export floor, first-call initial-SOC bound, total recovery-energy bound)", "primary_gap": "relaxed_bound - exact chronological network-LP endpoint", "cluster": "date-cluster bootstrap, 5000 replicates, seed 20261003"},
        "source_hashes": {"bounds": sha256(bounds_path), "policy": sha256(policy_path)},
        "files": ["contract_gap_rows.csv", "contract_gap_summary.csv", "metadata.json"],
        "limitations": ["scalar dispatch under frozen audited AC bounds", "no OpenDSS replay in this grid", "single IEEE-13 feeder and two primary placements"],
    }
    metadata["script_sha256"] = sha256(Path(__file__).resolve())
    metadata["python_runtime"] = sys.version.split()[0]
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return {"metadata": metadata, "summary_rows": int(len(summary)), "detail_rows": int(len(detail))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bounds", type=Path, default=DEFAULT_BOUNDS)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    print(json.dumps(run(args.bounds, args.policy, args.out_dir), indent=2))
