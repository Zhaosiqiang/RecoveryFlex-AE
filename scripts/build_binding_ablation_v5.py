#!/usr/bin/env python3
"""Audit whether the network frontier is already a service-window export bound.

The strict-v5 manuscript uses an AC-derived scalar export limit for each
profile interval.  This audit asks a narrow, pre-specified question: for the
two service windows, is the 2-MWh network-LP endpoint equal to the minimum
audited export limit, and when does a smaller battery fall below that bound?

The script reads the CSV files produced by the existing experiments.  It does
not run OpenDSS or rerun the dispatch planner, and it does not alter any
manuscript, figure, or submission-package file.  The primary population is
``baseline_feasible`` (the same conditional population used by the manuscript);
all rows are also reported as a diagnostic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SERVICE_INTERVALS = (8, 9, 10, 11, 24, 25, 26, 27)
CAPACITIES = (250.0, 500.0, 1000.0, 2000.0)
TOLERANCE_KW = 1.0e-9
KEYS = ["date", "day_index", "group", "site"]

DEFAULT_OUT = ROOT / "results" / "binding_ablation_strict_v5"
SOURCES = {
    "ausgrid": {
        "bounds": ROOT / "results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv",
        "primary_policy": ROOT / "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv",
        "capacity_policy": ROOT / "results/capacity_sensitivity_strict_v4/policy_rows.csv",
    },
    "opsd": {
        "bounds": ROOT / "results/opsd_cross_source_strict_v5/ac_bounds.csv",
        "primary_policy": ROOT / "results/opsd_cross_source_strict_v5/policy_rows.csv",
        "capacity_policy": None,
    },
}


def _normalise_keys(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    missing = sorted(set(KEYS) - set(frame.columns))
    if missing:
        raise ValueError(f"{path}: missing key columns {missing}")
    out = frame.copy()
    out["date"] = out["date"].astype(str)
    out["day_index"] = pd.to_numeric(out["day_index"], errors="raise").astype(int)
    out["group"] = pd.to_numeric(out["group"], errors="raise").astype(int)
    out["site"] = out["site"].astype(str)
    return out


def _check_unique(frame: pd.DataFrame, keys: list[str], path: Path) -> None:
    duplicate = frame.duplicated(keys, keep=False)
    if duplicate.any():
        sample = frame.loc[duplicate, keys].head(5).to_dict("records")
        raise ValueError(f"{path}: duplicate rows for {keys}: {sample}")


def _read_bounds(path: Path) -> pd.DataFrame:
    bounds = _normalise_keys(pd.read_csv(path), path)
    required = {"interval", "export_limit_kw"}
    missing = sorted(required - set(bounds.columns))
    if missing:
        raise ValueError(f"{path}: missing bound columns {missing}")
    bounds["interval"] = pd.to_numeric(bounds["interval"], errors="raise").astype(int)
    bounds["export_limit_kw"] = pd.to_numeric(bounds["export_limit_kw"], errors="raise")
    _check_unique(bounds, KEYS + ["interval"], path)
    counts = bounds.groupby(KEYS, sort=False)["interval"].nunique()
    bad = counts[counts != 48]
    if not bad.empty:
        raise ValueError(f"{path}: expected 48 intervals per unit, got {bad.head().to_dict()}")
    service = bounds[bounds["interval"].isin(SERVICE_INTERVALS)].copy()
    service_counts = service.groupby(KEYS, sort=False)["interval"].nunique()
    bad_service = service_counts[service_counts != len(SERVICE_INTERVALS)]
    if not bad_service.empty:
        raise ValueError(
            f"{path}: expected {len(SERVICE_INTERVALS)} service intervals per unit, "
            f"got {bad_service.head().to_dict()}"
        )
    return (
        service.groupby(KEYS, as_index=False, sort=False)["export_limit_kw"]
        .min()
        .rename(columns={"export_limit_kw": "min_service_export_kw"})
    )


def _read_policy(path: Path) -> pd.DataFrame:
    policy = _normalise_keys(pd.read_csv(path), path)
    required = {"method", "service_kw", "baseline_feasible"}
    missing = sorted(required - set(policy.columns))
    if missing:
        raise ValueError(f"{path}: missing policy columns {missing}")
    policy["method"] = policy["method"].astype(str)
    policy["service_kw"] = pd.to_numeric(policy["service_kw"], errors="raise")
    policy["baseline_feasible"] = pd.to_numeric(
        policy["baseline_feasible"], errors="raise"
    ).astype(int)
    _check_unique(policy, KEYS + ["method"] + (["capacity_kwh"] if "capacity_kwh" in policy else []), path)
    return policy


def _merge_network(policy: pd.DataFrame, minima: pd.DataFrame) -> pd.DataFrame:
    network = policy[policy["method"].eq("network_lp")].copy()
    if "capacity_kwh" in network:
        network = network[network["capacity_kwh"].eq(2000.0)].copy()
    _check_unique(network, KEYS, Path("network policy table"))
    merged = network.merge(minima, on=KEYS, how="left", validate="one_to_one")
    if merged["min_service_export_kw"].isna().any():
        raise ValueError("network policy rows did not all match service-window bounds")
    merged["delta_kw"] = merged["service_kw"] - merged["min_service_export_kw"]
    merged["equal_exact"] = merged["delta_kw"].eq(0.0)
    merged["equal_tolerance"] = merged["delta_kw"].abs().le(TOLERANCE_KW)
    merged["below_min_export"] = merged["delta_kw"].lt(-TOLERANCE_KW)
    return merged


def _merge_capacity(policy: pd.DataFrame, minima: pd.DataFrame) -> pd.DataFrame:
    required = {"capacity_kwh"}
    missing = sorted(required - set(policy.columns))
    if missing:
        raise ValueError(f"capacity policy table: missing columns {missing}")
    network = policy[(policy["method"].eq("network_lp"))].copy()
    network["capacity_kwh"] = pd.to_numeric(network["capacity_kwh"], errors="raise")
    observed = set(float(x) for x in network["capacity_kwh"].unique())
    if observed != set(CAPACITIES):
        raise ValueError(f"capacity policy table: expected capacities {CAPACITIES}, got {sorted(observed)}")
    merged = network.merge(minima, on=KEYS, how="left", validate="many_to_one")
    if merged["min_service_export_kw"].isna().any():
        raise ValueError("capacity policy rows did not all match service-window bounds")
    merged["delta_kw"] = merged["service_kw"] - merged["min_service_export_kw"]
    merged["equal_exact"] = merged["delta_kw"].eq(0.0)
    merged["equal_tolerance"] = merged["delta_kw"].abs().le(TOLERANCE_KW)
    merged["below_min_export"] = merged["delta_kw"].lt(-TOLERANCE_KW)
    return merged


def _population(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if name == "all":
        return frame
    if name == "baseline_feasible":
        return frame[frame["baseline_feasible"].eq(1)]
    raise ValueError(name)


def _equality_summary(source: str, frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for site, sf in frame.groupby("site", sort=True):
        for population in ("all", "baseline_feasible"):
            pf = _population(sf, population)
            rows.append(
                {
                    "source": source,
                    "site": site,
                    "population": population,
                    "n_units": int(len(pf)),
                    "n_equal_exact": int(pf["equal_exact"].sum()),
                    "n_equal_tolerance": int(pf["equal_tolerance"].sum()),
                    "n_below_min_export": int(pf["below_min_export"].sum()),
                    "max_abs_delta_kw": float(pf["delta_kw"].abs().max()),
                    "mean_delta_kw": float(pf["delta_kw"].mean()),
                }
            )
    return pd.DataFrame(rows)


def _capacity_summary(source: str, frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for site, sf in frame.groupby("site", sort=True):
        for capacity, cf in sf.groupby("capacity_kwh", sort=True):
            for population in ("all", "baseline_feasible"):
                pf = _population(cf, population).copy()
                if pf.empty:
                    continue
                date_means = pf.groupby("date", sort=True)["delta_kw"].mean()
                date_below = pf.groupby("date", sort=True)["below_min_export"].mean()
                rows.append(
                    {
                        "source": source,
                        "site": site,
                        "capacity_kwh": float(capacity),
                        "population": population,
                        "n_units": int(len(pf)),
                        "n_dates": int(pf["date"].nunique()),
                        "n_below_min_export": int(pf["below_min_export"].sum()),
                        "proportion_below_min_export": float(pf["below_min_export"].mean()),
                        "date_mean_proportion_below_min_export": float(date_below.mean()),
                        "mean_unit_delta_kw": float(pf["delta_kw"].mean()),
                        "date_mean_delta_kw": float(date_means.mean()),
                        "date_mean_abs_delta_kw": float(pf.groupby("date")["delta_kw"].mean().abs().mean()),
                        "min_delta_kw": float(pf["delta_kw"].min()),
                        "max_delta_kw": float(pf["delta_kw"].max()),
                    }
                )
    return pd.DataFrame(rows)


def run(out_dir: Path = DEFAULT_OUT) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    equality_frames: list[pd.DataFrame] = []
    equality_summary: list[pd.DataFrame] = []
    capacity_frames: list[pd.DataFrame] = []
    capacity_summary: list[pd.DataFrame] = []
    metadata: dict[str, object] = {
        "status": "binding_ablation_strict_v5",
        "service_intervals": list(SERVICE_INTERVALS),
        "tolerance_kw": TOLERANCE_KW,
        "capacities_kwh": list(CAPACITIES),
        "primary_population": "baseline_feasible",
        "sources": {},
    }

    for source, paths in SOURCES.items():
        for label in ("bounds", "primary_policy"):
            if not paths[label].exists():
                raise FileNotFoundError(paths[label])
        minima = _read_bounds(paths["bounds"])
        primary = _read_policy(paths["primary_policy"])
        eq = _merge_network(primary, minima)
        eq.insert(0, "source", source)
        equality_frames.append(eq)
        equality_summary.append(_equality_summary(source, eq))
        meta_source: dict[str, object] = {
            "bounds": str(paths["bounds"]),
            "primary_policy": str(paths["primary_policy"]),
            "n_primary_units": int(len(eq)),
        }
        if paths["capacity_policy"] is not None:
            if not paths["capacity_policy"].exists():
                raise FileNotFoundError(paths["capacity_policy"])
            capacity = _read_policy(paths["capacity_policy"])
            cap = _merge_capacity(capacity, minima)
            cap.insert(0, "source", source)
            capacity_frames.append(cap)
            capacity_summary.append(_capacity_summary(source, cap))
            # Confirm that the capacity table's 2-MWh endpoint is exactly the
            # same CSV endpoint used by the primary experiment.
            primary_compare = eq[KEYS + ["service_kw"]].rename(columns={"service_kw": "primary_2mwh_kw"})
            capacity_compare = cap[cap["capacity_kwh"].eq(2000.0)][KEYS + ["service_kw"]].rename(columns={"service_kw": "capacity_2mwh_kw"})
            compare = primary_compare.merge(capacity_compare, on=KEYS, validate="one_to_one")
            compare_delta = compare["capacity_2mwh_kw"] - compare["primary_2mwh_kw"]
            meta_source["capacity_2mwh_vs_primary_max_abs_delta_kw"] = float(compare_delta.abs().max())
            meta_source["capacity_policy"] = str(paths["capacity_policy"])
        metadata["sources"][source] = meta_source

    equality_all = pd.concat(equality_frames, ignore_index=True)
    equality_all.to_csv(out_dir / "two_mwh_binding_by_unit.csv", index=False)
    pd.concat(equality_summary, ignore_index=True).to_csv(out_dir / "two_mwh_binding_summary.csv", index=False)
    if capacity_frames:
        capacity_all = pd.concat(capacity_frames, ignore_index=True)
        capacity_all.to_csv(out_dir / "capacity_binding_by_unit.csv", index=False)
        pd.concat(capacity_summary, ignore_index=True).to_csv(out_dir / "capacity_binding_summary.csv", index=False)

    (out_dir / "summary.json").write_text(json.dumps(metadata, indent=2) + "\n")
    _write_audit_text(out_dir, equality_all, capacity_frames, metadata)
    _write_readme(out_dir)
    _write_recovery_design(out_dir)


def _write_audit_text(out_dir: Path, equality: pd.DataFrame, capacities: list[pd.DataFrame], metadata: dict[str, object]) -> None:
    lines = [
        "Binding ablation audit (strict-v5 CSVs)",
        "",
        "Question: does the 2-MWh network-LP endpoint equal the minimum audited export limit over service intervals [8,12) and [24,28), and when does a smaller capacity fall below it?",
        "Service intervals (zero-based half-hour positions): 8,9,10,11,24,25,26,27.",
        f"Equality tolerance: {TOLERANCE_KW:.1e} kW; exact equality is also reported.",
        "The primary population is baseline_feasible; all rows are retained as a diagnostic.",
        "",
        "2-MWh equality summary:",
    ]
    eqs = _equality_summary_from_combined(equality)
    for r in eqs.itertuples(index=False):
        lines.append(
            f"  {r.source} site={r.site} population={r.population}: n={r.n_units}, "
            f"exact={r.n_equal_exact}/{r.n_units}, tol={r.n_equal_tolerance}/{r.n_units}, "
            f"max|delta|={r.max_abs_delta_kw:.12g} kW, below={r.n_below_min_export}"
        )
    lines += ["", "Capacity summary (network_lp only; delta = frontier - min service-window export):"]
    if capacities:
        cs = _capacity_summary_from_combined(pd.concat(capacities, ignore_index=True))
        for r in cs[cs.population.eq("baseline_feasible")].itertuples(index=False):
            lines.append(
                f"  {r.source} site={r.site} E={r.capacity_kwh:g} kWh: "
                f"below={r.proportion_below_min_export:.6f} ({r.n_below_min_export}/{r.n_units}), "
                f"date-mean delta={r.date_mean_delta_kw:.6f} kW, "
                f"unit-mean delta={r.mean_unit_delta_kw:.6f} kW"
            )
    lines += [
        "",
        "Interpretation: equality means the full-horizon LP is capped by the tightest service-window export bound for that unit. A negative delta means the chronological SOC/recovery constraints (or the capacity setting) lower the frontier below that network bound. This is an ablation of the existing CSV endpoints, not a new AC solve or a causal attribution of all physical limits.",
        "",
        "The source and file paths used are recorded in summary.json.",
    ]
    (out_dir / "AUDIT.txt").write_text("\n".join(lines) + "\n")


def _equality_summary_from_combined(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([_equality_summary(source, sf) for source, sf in frame.groupby("source", sort=True)], ignore_index=True)


def _capacity_summary_from_combined(frame: pd.DataFrame) -> pd.DataFrame:
    return pd.concat([_capacity_summary(source, sf) for source, sf in frame.groupby("source", sort=True)], ignore_index=True)


def _write_readme(out_dir: Path) -> None:
    text = """# Strict-v5 binding ablation

This directory is a read-only audit of the existing Ausgrid strict-v4 and OPSD strict-v5 CSV outputs. It does not run OpenDSS or modify the manuscript.

`two_mwh_binding_by_unit.csv` compares each 2-MWh `network_lp` endpoint with the minimum `export_limit_kw` across the eight service intervals (8--11 and 24--27). `two_mwh_binding_summary.csv` reports exact and tolerance-based equality for all rows and for the manuscript's `baseline_feasible` population.

`capacity_binding_by_unit.csv` and `capacity_binding_summary.csv` perform the same comparison for the Ausgrid network-LP capacity rows at 250, 500, 1000, and 2000 kWh. `date_mean_delta_kw` first averages groups within each date and then averages dates equally, matching the manuscript's primary estimator within each placement. `AUDIT.txt` gives a compact deterministic report; `summary.json` records inputs and checks.

A negative delta is `network frontier - minimum service-window export bound`. It shows that the dispatch endpoint is below the tightest service-window export bound. Equality is a binding check, not proof that no other network or SOC constraint is active elsewhere in the schedule.
"""
    (out_dir / "README.md").write_text(text)


def _write_recovery_design(out_dir: Path) -> None:
    text = """Predefined recovery-constraint experiment (for a future run)

Purpose
-------
The binding audit shows whether the current 2-MWh network endpoint is capped
by the tightest service-window export bound.  The following experiment is a
predeclared test of when chronological recovery becomes the active constraint;
all grid points are run before looking at their outcomes, so no window or
capacity is selected from the results.

Frozen data and network protocol
--------------------------------
Use every retained Ausgrid strict-v4 date, group, and the two existing battery
placements, plus every held-out OPSD date and its two placements.  Keep the
existing zero-power baseline gate, profile embedding, OpenDSS snapshot bounds,
voltage/loading limits, efficiencies, initial SOC (0.80), terminal SOC (0.80),
service windows [8,12) and [24,28), and the current 48 half-hour horizon.  Do
not reselect dates, groups, sites, or profiles after inspecting results.

Predefined grid
---------------
Battery energy: E in {250, 500, 750, 1000, 1500, 2000} kWh.
Recovery-window delay: delta in {0, 2, 4, 6} half-hour intervals, with

    R_delta = [12+delta, 24) union [28+delta, 48).

The service windows remain fixed.  delta=0 reproduces the current protocol;
the other three values remove early post-call recovery opportunities while
leaving the service obligation unchanged.  Every (E, delta) combination is a
planned cell (24 cells per placement and source), including cells that may be
infeasible.

Estimands and checks
--------------------
For every date x group x placement x (E, delta), compute the full-horizon
network-LP endpoint and the fixed-recovery comparator using only the audited
scalar bounds.  Define b = min export_limit_kw over the eight service
intervals, delta_P = P_frontier - b, and I_recovery = 1[delta_P < -1e-9 kW].
Report, for every grid cell and site, the unit proportion I_recovery=1,
the date-cluster mean delta_P (groups averaged within date first), the
date-cluster bootstrap interval, planner-feasibility rate, and—where the
frontier schedule is replayed—the AC replay rate.  Also report the exact
2-MWh equality check as a protocol-control cell.  Keep all rows; do not
condition on a successful endpoint except for the separately labelled primary
baseline-feasible population.

Validation and interpretation
-----------------------------
Re-run the existing bound table only once; changing E or delta changes the
chronological dispatch, not the snapshot feeder state.  Replay every selected
frontier schedule through OpenDSS if computationally feasible; otherwise
predeclare a fixed, stratified replay sample before opening any endpoint
results (seed 20261004, all sites x all E x all delta, 20 dates per cell).
Never call a scalar-bound cell an AC validation.  Do not select the maximum
cell, a preferred delay, or a capacity threshold after seeing the surface.
The main test is the complete 6 x 4 surface; a secondary summary may report
the smallest E at each delta whose date-mean frontier reaches 95% of its
delta=0, E=2000 reference, but that threshold must be evaluated at the fixed
predeclared grid and cannot be interpolated or optimized post hoc.

Falsifiable interpretation
--------------------------
If the current binding explanation is correct, high-capacity, early-recovery
cells should remain close to b while reducing E or delaying recovery should
produce a reproducible negative delta_P and a rising I_recovery.  If the whole
surface remains equal to b, the repeated-contract recovery constraint is not
active for this feeder/profile protocol and the manuscript should not present
recovery as a dominant mechanism.  This design tests that statement without
choosing time windows or capacity levels after observing the data.
"""
    (out_dir / "recovery_constraint_design.txt").write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    run(args.out)
    print(f"Wrote binding ablation outputs to {args.out}")
