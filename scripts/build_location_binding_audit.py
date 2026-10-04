#!/usr/bin/env python3
"""Audit service-window binding for the completed seven-site placement run.

This post-processing audit joins the placement-run AC export bounds to the
network-LP endpoint.  It does not rerun OpenDSS or dispatch.  The result is a
placement-conditioned check of whether the 2-MWh endpoint equals the minimum
service-window export envelope.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


SERVICE_INTERVALS = (8, 9, 10, 11, 24, 25, 26, 27)
TOLERANCE_KW = 1.0e-9
SITES = ("611.3", "634.1", "675.1", "652.1", "645.3", "646.3", "684.3")
KEYS = ["date", "day_index", "group", "site"]


def _keys(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    missing = sorted(set(KEYS) - set(frame.columns))
    if missing:
        raise ValueError(f"{path}: missing keys {missing}")
    out = frame.copy()
    out["date"] = out["date"].astype(str)
    out["site"] = out["site"].astype(str)
    out["day_index"] = pd.to_numeric(out["day_index"], errors="raise").astype(int)
    out["group"] = pd.to_numeric(out["group"], errors="raise").astype(int)
    return out


def run(results_dir: Path, out_dir: Path) -> None:
    bounds_path = results_dir / "ac_bounds.csv"
    policy_path = results_dir / "policy_rows.csv"
    bounds = _keys(pd.read_csv(bounds_path), bounds_path)
    policy = _keys(pd.read_csv(policy_path), policy_path)
    bounds["interval"] = pd.to_numeric(bounds["interval"], errors="raise").astype(int)
    bounds["export_limit_kw"] = pd.to_numeric(bounds["export_limit_kw"], errors="raise")
    if bounds.duplicated(KEYS + ["interval"]).any():
        raise ValueError("duplicate AC bound rows")
    counts = bounds.groupby(KEYS)["interval"].nunique()
    if not counts.eq(48).all():
        raise ValueError("each placement unit must have 48 AC-bound intervals")
    minima = (
        bounds[bounds["interval"].isin(SERVICE_INTERVALS)]
        .groupby(KEYS, as_index=False)["export_limit_kw"]
        .min()
        .rename(columns={"export_limit_kw": "min_service_export_kw"})
    )

    network = policy[policy["method"].eq("network_lp")].copy()
    if network.duplicated(KEYS).any():
        raise ValueError("duplicate network-LP placement rows")
    network["service_kw"] = pd.to_numeric(network["service_kw"], errors="raise")
    network["baseline_feasible"] = pd.to_numeric(network["baseline_feasible"], errors="raise").astype(int)
    merged = network.merge(minima, on=KEYS, how="left", validate="one_to_one")
    if merged["min_service_export_kw"].isna().any():
        raise ValueError("missing service-window export bound")
    merged["delta_kw"] = merged["service_kw"] - merged["min_service_export_kw"]
    merged["equal_exact"] = merged["delta_kw"].eq(0.0)
    merged["equal_tolerance"] = merged["delta_kw"].abs().le(TOLERANCE_KW)
    merged["below_min_export"] = merged["delta_kw"].lt(-TOLERANCE_KW)
    merged = merged.sort_values(KEYS).reset_index(drop=True)

    rows = []
    for site, sf in merged.groupby("site", sort=False):
        for population, pf in (("all", sf), ("baseline_feasible", sf[sf["baseline_feasible"].eq(1)])):
            rows.append({
                "site": site,
                "population": population,
                "n_units": int(len(pf)),
                "n_equal_exact": int(pf["equal_exact"].sum()),
                "n_equal_tolerance": int(pf["equal_tolerance"].sum()),
                "n_below_min_export": int(pf["below_min_export"].sum()),
                "max_abs_delta_kw": float(pf["delta_kw"].abs().max()) if len(pf) else float("nan"),
                "mean_delta_kw": float(pf["delta_kw"].mean()) if len(pf) else float("nan"),
            })
    summary = pd.DataFrame(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_dir / "two_mwh_binding_by_unit.csv", index=False)
    summary.to_csv(out_dir / "two_mwh_binding_summary.csv", index=False)
    (out_dir / "AUDIT.txt").write_text(
        "Placement binding audit\n\n"
        "The network-LP 2-MWh endpoint is compared with the minimum audited export limit over service intervals 8,9,10,11,24,25,26,27.\n"
        f"Equality tolerance: {TOLERANCE_KW:.1e} kW.\n"
        "The primary population is baseline_feasible; all rows are retained as a diagnostic.\n\n"
        + "\n".join(
            f"site={r.site} population={r.population}: n={r.n_units}, exact={r.n_equal_exact}/{r.n_units}, "
            f"tol={r.n_equal_tolerance}/{r.n_units}, below={r.n_below_min_export}, max|delta|={r.max_abs_delta_kw:.12g} kW"
            for r in summary.itertuples(index=False)
        )
        + "\n\nThis is a post-processing decomposition of the frozen scalar-bound endpoints; it is not a causal attribution or a new AC solve.\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.results_dir, args.out_dir)


if __name__ == "__main__":
    main()
