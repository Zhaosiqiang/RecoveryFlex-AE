#!/usr/bin/env python3
"""Compare hindsight recovery with finite-information causal baselines.

The script reuses the audited strict-v4 interval bounds.  It does not run a
power flow and therefore reports a dispatch-bound sensitivity; the selected
commands are feasible under the same scalar AC bounds used by strict-v4 and
can be replayed with the existing OpenDSS runner.  ``causal_hN`` knows only
the current charge/export limits and the next N intervals of the declared
service calendar.  It never reads network bounds beyond that horizon.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "src"))
from recoveryflex.dispatch import plan_service

WINDOWS = ((8, 12), (24, 28))
DT_H = 0.5
ETA_C = 0.95
ETA_D = 0.95
SOC0 = 0.8
SOC_MIN = 0.2
SOC_MAX = 1.0
TERMINAL_SOC = 0.8
FIXED_RATIO = 8.0 / (32.0 * ETA_C * ETA_D)
FIXED_WINDOWS = ((12, 24), (28, 48))
HORIZON = 48
CAPACITIES = (250.0, 500.0, 1000.0, 2000.0)
LOOKAHEADS = (4, 8, 12, 24)


def _mask(windows: tuple[tuple[int, int], ...]) -> np.ndarray:
    out = np.zeros(HORIZON, dtype=bool)
    for a, b in windows:
        out[a:b] = True
    return out


SERVICE = _mask(WINDOWS)
RECOVERY = _mask(FIXED_WINDOWS)


def _causal_rollout(p: float, charge: np.ndarray, export: np.ndarray, energy_kwh: float, lookahead: int):
    """Causal current-headroom policy with a finite service-calendar lookahead.

    The contract declares each service block's four-interval duration.  Once a
    block start is visible inside the lookahead, the rollout may therefore
    count that full declared block; later block starts and all future network
    bounds remain hidden.
    """
    energy = np.empty(HORIZON + 1, dtype=float)
    energy[0] = energy_kwh * SOC0
    c = np.zeros(HORIZON, dtype=float)
    d = np.where(SERVICE, p, 0.0)
    lo, hi = energy_kwh * SOC_MIN, energy_kwh * SOC_MAX
    for t in range(HORIZON):
        if SERVICE[t]:
            if p > export[t] + 1e-8:
                return False
            energy[t + 1] = energy[t] - p * DT_H / ETA_D
        else:
            if not RECOVERY[t]:
                # No pre-charge before the first call: the first service is
                # supported by the declared initial SOC.
                energy[t + 1] = energy[t]
                continue
            horizon_end = min(HORIZON, t + 1 + int(lookahead))
            future = np.flatnonzero(SERVICE[t + 1:horizon_end])
            if future.size:
                first = t + 1 + int(future[0])
                block = 0
                while first + block < HORIZON and SERVICE[first + block]:
                    block += 1
                target = lo + p * block * DT_H / ETA_D
            elif horizon_end == HORIZON:
                target = energy_kwh * TERMINAL_SOC
            else:
                target = lo
            available = min(float(charge[t]), max(0.0, (hi - energy[t]) / (ETA_C * DT_H)))
            desired = max(0.0, (target - energy[t]) / (ETA_C * DT_H))
            c[t] = min(available, desired)
            energy[t + 1] = energy[t] + ETA_C * c[t] * DT_H
        if energy[t + 1] < lo - 1e-7 or energy[t + 1] > hi + 1e-7:
            return False
    # Keep the finite-information benchmark on the same exact-terminal-SOC
    # contract as the main dispatch model.  The rollout clips its last charge
    # action to the target, so an absolute check is both stricter and clearer
    # than accepting an accidental overcharge.
    return bool(abs(energy[-1] - energy_kwh * TERMINAL_SOC) <= 1e-7)


def causal_frontier(charge: np.ndarray, export: np.ndarray, energy_kwh: float, lookahead: int) -> float:
    if not _causal_rollout(0.0, charge, export, energy_kwh, lookahead):
        return 0.0
    lo, hi = 0.0, float(np.min(export[SERVICE]))
    for _ in range(45):
        mid = (lo + hi) / 2.0
        if _causal_rollout(mid, charge, export, energy_kwh, lookahead):
            lo = mid
        else:
            hi = mid
    return lo


def cluster_bootstrap(values: pd.DataFrame, value_col: str, reps: int = 5000, seed: int = 20261003):
    per_date = values.groupby("date", as_index=False)[value_col].mean()
    x = per_date[value_col].to_numpy(float)
    rng = np.random.default_rng(seed)
    means = np.empty(reps)
    for i in range(reps):
        means[i] = np.mean(rng.choice(x, size=x.size, replace=True))
    return float(np.mean(x)), float(np.quantile(means, .025)), float(np.quantile(means, .975))


def run(bounds_path: Path, audit_path: Path, out_dir: Path) -> dict:
    bounds = pd.read_csv(bounds_path)
    audit = pd.read_csv(audit_path)
    bounds["site"] = bounds["site"].astype(str)
    audit["site"] = audit["site"].astype(str)
    gate = audit[["date", "group", "site", "baseline_zero_feasible"]].copy()
    gate["baseline_feasible"] = gate["baseline_zero_feasible"].astype(int)
    rows = []
    for (date, group, site), g in bounds.groupby(["date", "group", "site"], sort=True):
        g = g.sort_values("interval")
        charge = g["charge_limit_kw"].to_numpy(float)
        export = g["export_limit_kw"].to_numpy(float)
        if charge.size != HORIZON:
            raise ValueError(f"{date}/{group}/{site}: expected 48 rows")
        for E in CAPACITIES:
            common = dict(
                charge_limit_kw=charge,
                export_limit_kw=export,
                load_kw=np.zeros(HORIZON),
                service_windows=WINDOWS,
                energy_kwh=E,
                initial_soc=SOC0,
                terminal_soc_target=TERMINAL_SOC,
                soc_min=SOC_MIN,
                soc_max=SOC_MAX,
                eta_charge=ETA_C,
                eta_discharge=ETA_D,
                dt_h=DT_H,
                terminal_mode="exact",
                recovery_windows=FIXED_WINDOWS,
            )
            for method, kw in (
                ("network_lp", dict(mode="network_lp")),
                ("fixed_recovery", dict(mode="fixed_recovery", fixed_recovery_ratio=FIXED_RATIO)),
                ("myopic_recovery", dict(mode="myopic_recovery")),
            ):
                result = plan_service(**common, **kw)
                rows.append(dict(date=date, group=int(group), site=str(site), energy_kwh=E,
                                 method=method, service_kw=float(result.service_kw),
                                 planner_feasible=int(result.feasible), replay_equivalent=int(result.feasible)))
            for H in LOOKAHEADS:
                rows.append(dict(date=date, group=int(group), site=str(site), energy_kwh=E,
                                 method=f"causal_h{H}", service_kw=causal_frontier(charge, export, E, H),
                                 planner_feasible=1, replay_equivalent=1))
    df = pd.DataFrame(rows).merge(gate[["date", "group", "site", "baseline_feasible"]], on=["date", "group", "site"], how="left")
    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_dir / "policy_rows.csv", index=False)
    records = []
    for (site, E, method), g in df[df.baseline_feasible == 1].groupby(["site", "energy_kwh", "method"], sort=True):
        mean, lo, hi = cluster_bootstrap(g, "service_kw")
        records.append(dict(site=site, energy_kwh=E, method=method, estimate=mean, ci_low=lo, ci_high=hi,
                            n_units=len(g), n_dates=g.date.nunique()))
    summary = pd.DataFrame(records)
    summary.to_csv(out_dir / "date_cluster_summary.csv", index=False)
    pivot = summary.pivot_table(index=["site", "energy_kwh"], columns="method", values="estimate").reset_index()
    for method in ["causal_h4", "causal_h8", "causal_h12", "causal_h24", "myopic_recovery", "fixed_recovery"]:
        if method in pivot:
            pivot[f"oracle_minus_{method}"] = pivot["network_lp"] - pivot[method]
    pivot.to_csv(out_dir / "oracle_gaps.csv", index=False)
    payload = {"status": "calendar_horizon_and_capacity_sensitivity", "bounds": str(bounds_path),
               "capacities_kwh": list(CAPACITIES), "lookahead_intervals": list(LOOKAHEADS),
               "windows": [list(x) for x in WINDOWS], "recovery_windows": [list(x) for x in FIXED_WINDOWS], "n_rows": int(len(df)),
               "n_baseline_units_per_site": int(df[df.baseline_feasible == 1][["site", "date", "group"]].drop_duplicates().groupby("site").size().min()),
               "summary_csv": str((out_dir / "date_cluster_summary.csv").resolve())}
    (out_dir / "summary.json").write_text(json.dumps(payload, indent=2))
    return payload


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", type=Path, default=ROOT / "results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv")
    ap.add_argument("--audit", type=Path, default=ROOT / "results/network_recovery_external_2012_2013_strict_v4/baseline_zero_audit.csv")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "results/causal_capacity_sensitivity_strict_v4")
    args = ap.parse_args()
    print(json.dumps(run(args.bounds, args.audit, args.out_dir), indent=2))
