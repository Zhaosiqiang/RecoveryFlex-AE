#!/usr/bin/env python3
"""Battery-capacity sensitivity using the frozen strict-v4 AC-bound table.

This is an dispatch sensitivity under frozen audited scalar bounds: no OpenDSS solves are
performed.  The audited charge/export limits are held fixed while the
chronological dispatch planner is rerun for several battery capacities.
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
sys.path.insert(0, str(ROOT / "scripts"))
from recoveryflex.dispatch import plan_service
from run_network_recovery_v2 import _embedded_external, WINDOWS, FIXED_RECOVERY_WINDOWS, REARM_RATIO
import run_corrected_experiment as exp
from recoveryflex.profile_bank import load_bank

SITES = ("611.3", "634.1")
METHODS = ("network_lp", "fixed_recovery", "myopic_recovery")
CAPACITIES = (250.0, 500.0, 1000.0, 2000.0)


def _summaries(rows: pd.DataFrame, seed: int = 20261003, n_boot: int = 5000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    records = []
    for population, frame in (("all", rows), ("baseline_feasible", rows[rows.baseline_feasible == 1])):
        for site in sorted(frame.site.unique()):
            sf = frame[frame.site == site]
            for capacity in sorted(sf.capacity_kwh.unique()):
                cf = sf[sf.capacity_kwh == capacity]
                for method in METHODS:
                    mf = cf[cf.method == method]
                    for outcome in ("service_kw", "planner_feasible"):
                        vals = mf[outcome].to_numpy(float)
                        clusters = mf.assign(_cluster=mf.date).groupby("_cluster")[outcome].mean().to_numpy(float)
                        draws = clusters[rng.integers(0, len(clusters), size=(n_boot, len(clusters)))].mean(axis=1) if len(clusters) > 1 else np.array([clusters.mean()])
                        records.append({"population": population, "site": site, "capacity_kwh": capacity,
                                        "method": method, "outcome": outcome, "cluster_level": "date",
                                        "estimate": float(clusters.mean()),
                                        "ci_low": float(np.quantile(draws, .025)), "ci_high": float(np.quantile(draws, .975)),
                                        "n_units": int(len(vals)), "n_dates": int(len(clusters))})
                        pooled_draws = vals[rng.integers(0, len(vals), size=(n_boot, len(vals)))].mean(axis=1)
                        records.append({"population": population, "site": site, "capacity_kwh": capacity,
                                        "method": method, "outcome": outcome, "cluster_level": "pooled",
                                        "estimate": float(vals.mean()),
                                        "ci_low": float(np.quantile(pooled_draws, .025)), "ci_high": float(np.quantile(pooled_draws, .975)),
                                        "n_units": int(len(vals)), "n_dates": int(len(clusters))})
    return pd.DataFrame(records)


def run(source: Path, bounds_path: Path, policy_path: Path, out_dir: Path) -> None:
    bounds = pd.read_csv(bounds_path)
    policy = pd.read_csv(policy_path)
    gate = policy[policy.method == "network_lp"][['date', 'day_index', 'group', 'site', 'baseline_feasible']].drop_duplicates()
    bounds = bounds.merge(gate, on=['date', 'day_index', 'group', 'site'], validate='many_to_one')
    dev = load_bank(exp.BANK_PATH)
    load, _pv, dates = _embedded_external(dev, source)
    date_to_day = {str(d): i for i, d in enumerate(dates)}
    rows = []
    for capacity in CAPACITIES:
        for (date, day_index, group, site), g in bounds.groupby(['date', 'day_index', 'group', 'site'], sort=False):
            if str(date) not in date_to_day:
                raise ValueError(f'date {date} missing from source')
            ld = load[date_to_day[str(date)], :48, int(group)]
            charge = g.sort_values('interval').charge_limit_kw.to_numpy(float)
            export = g.sort_values('interval').export_limit_kw.to_numpy(float)
            common = dict(charge_limit_kw=charge, export_limit_kw=export, load_kw=ld,
                          service_windows=WINDOWS, energy_kwh=capacity, initial_soc=exp.SOC_INITIAL,
                          terminal_soc_target=exp.SOC_INITIAL, soc_min=exp.SOC_RESERVE, soc_max=1.0,
                          eta_charge=exp.ETA_CHARGE, eta_discharge=exp.ETA_DISCHARGE, dt_h=exp.DT_H,
                          terminal_mode='exact', recovery_windows=FIXED_RECOVERY_WINDOWS)
            modes = {'network_lp': {'mode': 'network_lp'},
                     'fixed_recovery': {'mode': 'fixed_recovery', 'fixed_recovery_ratio': REARM_RATIO,
                                        },
                     'myopic_recovery': {'mode': 'myopic_recovery'}}
            for method, kw in modes.items():
                result = plan_service(**common, **kw)
                rows.append({'date': str(date), 'day_index': int(day_index), 'group': int(group), 'site': str(site),
                             'capacity_kwh': capacity, 'method': method, 'service_kw': result.service_kw,
                             'planner_feasible': int(result.feasible), 'baseline_feasible': int(g.baseline_feasible.iloc[0]),
                             'terminal_soc': result.terminal_soc, 'message': result.message})
    out_dir.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame(rows)
    result.to_csv(out_dir / 'policy_rows.csv', index=False)
    summaries = _summaries(result)
    summaries.to_csv(out_dir / 'statistics.csv', index=False)
    meta = {'capacities_kwh': list(CAPACITIES), 'methods': list(METHODS), 'n_rows': int(len(result)),
            'n_units': int(result[['date','group','site']].drop_duplicates().shape[0]),
            'source_bounds': str(bounds_path), 'protocol': 'dispatch sensitivity under frozen audited scalar bounds; no OpenDSS rerun',
            'service_windows': [list(x) for x in WINDOWS], 'fixed_recovery_windows': [list(x) for x in FIXED_RECOVERY_WINDOWS],
            'bootstrap': {'seed': 20261003, 'n_boot': 5000, 'cluster': 'date'}}
    (out_dir / 'summary.json').write_text(json.dumps(meta, indent=2) + '\n')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=False)
    for ax, site in zip(axes, SITES):
        sf = summaries[(summaries.population == 'baseline_feasible') & (summaries.site == site) & (summaries.outcome == 'service_kw') & (summaries.cluster_level == 'date')]
        labels = {"network_lp": "AC-bound LP", "fixed_recovery": "Fixed recovery", "myopic_recovery": "Myopic recovery"}
        for method in METHODS:
            m = sf[sf.method == method].sort_values('capacity_kwh')
            ax.plot(m.capacity_kwh, m.estimate, marker='o', label=labels[method])
            ax.fill_between(m.capacity_kwh, m.ci_low, m.ci_high, alpha=.12)
        ax.set_title(f'Site {site}'); ax.set_xlabel('Battery capacity (kWh)'); ax.grid(alpha=.25)
    axes[0].set_ylabel('Service frontier (kW)'); axes[1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(out_dir / 'capacity_frontier.png', dpi=300); fig.savefig(out_dir / 'capacity_frontier.pdf'); plt.close(fig)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, default=ROOT / 'data/processed/ausgrid_external_2012_2013_strict.npz')
    ap.add_argument('--bounds', type=Path, default=ROOT / 'results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv')
    ap.add_argument('--policy', type=Path, default=ROOT / 'results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv')
    ap.add_argument('--out', type=Path, default=ROOT / 'results/capacity_sensitivity_strict_v4')
    args = ap.parse_args(); run(args.source, args.bounds, args.policy, args.out)
