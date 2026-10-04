#!/usr/bin/env python3
"""Small customer-to-group mapping sensitivity audit.

The headline external NPZ stores ten group means, so a mapping sensitivity
cannot be recovered from the NPZ alone.  This script goes back to the public
customer-level 2010--2011 and 2012--2013 CSV extracts, reconstructs the same
48-point load/PV profiles, and evaluates two alternative deterministic
30-customer groupings on a predeclared sample.  Train-only normalization is
recomputed for each grouping.  Fresh IEEE-13 snapshot bounds and the same
scalar two-call contract are used; this is a diagnostic, not a replacement
for the 2,190-unit headline result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from recoveryflex.dispatch import plan_service
from recoveryflex.ac_snapshot import ACSnapshotFeeder
import run_corrected_experiment as exp
import run_network_recovery_v2 as protocol


DEV_CSV = ROOT / "data/raw/ausgrid/Solar home 2010-2011.csv"
EXT_CSV = ROOT / "data/raw/ausgrid/2012_2013_extract/2012-2013 Solar home electricity data v2.csv"
STRICT_NPZ = ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _parse_customer_csv(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = pd.read_csv(path, skiprows=[0])
    # The two public extracts use slightly different day-first spellings
    # (``1-Jul-10`` versus ``1/07/2012``); ``mixed`` keeps parsing explicit
    # and avoids locale-dependent per-value fallbacks in pandas.
    raw["date"] = pd.to_datetime(raw["date"], format="mixed", dayfirst=True, errors="coerce")
    raw["Customer"] = pd.to_numeric(raw["Customer"], errors="coerce").astype("Int64")
    tcols = [str(c) for c in raw.columns if ":" in str(c)]
    if len(tcols) != 48:
        raise ValueError(f"{path}: expected 48 time columns, got {len(tcols)}")
    for c in tcols:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    customers = np.array(sorted(raw["Customer"].dropna().astype(int).unique()), dtype=int)
    dates = pd.DatetimeIndex(sorted(raw["date"].dropna().unique()))
    base = pd.MultiIndex.from_product([customers, dates], names=["Customer", "date"])
    grouped = (raw[raw["Consumption Category"].isin(["GC", "CL", "GG"])]
               .groupby(["Customer", "date", "Consumption Category"], sort=True)[tcols]
               .mean())
    arrays: dict[str, np.ndarray] = {}
    present: dict[str, np.ndarray] = {}
    for cat in ("GC", "CL", "GG"):
        if cat in grouped.index.get_level_values("Consumption Category"):
            frame = grouped.xs(cat, level="Consumption Category").reindex(base)
            present[cat] = frame.notna().all(axis=1).to_numpy().reshape(len(customers), len(dates))
            arrays[cat] = frame.fillna(0.0).to_numpy(float).reshape(len(customers), len(dates), 48)
        else:
            arrays[cat] = np.zeros((len(customers), len(dates), 48), dtype=float)
            present[cat] = np.zeros((len(customers), len(dates)), dtype=bool)
    load = (arrays["GC"] + arrays["CL"]) / 0.5
    pv = arrays["GG"] / 0.5
    valid = present["GC"] & present["GG"]
    # Keep a customer×date matrix so the mapping operation can be repeated
    # exactly with a different partition of the same 300 customers.
    return customers, dates.to_numpy(), load, pv, valid


def _group_profiles(load: np.ndarray, pv: np.ndarray, mapping: list[np.ndarray], date_idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n_dates = len(date_idx)
    out_l = np.zeros((n_dates, 48, len(mapping)), dtype=float)
    out_p = np.zeros_like(out_l)
    for gi, members in enumerate(mapping):
        out_l[:, :, gi] = load[members][:, date_idx, :].mean(axis=0)
        out_p[:, :, gi] = pv[members][:, date_idx, :].mean(axis=0)
    return out_l, out_p


def _dispatch(charge: np.ndarray, export: np.ndarray, load: np.ndarray):
    return plan_service(
        charge_limit_kw=charge,
        export_limit_kw=export,
        load_kw=load,
        service_windows=protocol.WINDOWS,
        recovery_windows=protocol.FIXED_RECOVERY_WINDOWS,
        energy_kwh=protocol.BATTERY_ENERGY_KWH,
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


def run(*, out_dir: Path, seeds: tuple[int, ...], days: tuple[int, ...], groups: tuple[int, ...]) -> dict[str, object]:
    dev_customers, dev_dates, dev_load, dev_pv, dev_valid = _parse_customer_csv(DEV_CSV)
    ext_customers, ext_dates, ext_load, ext_pv, ext_valid = _parse_customer_csv(EXT_CSV)
    if not np.array_equal(dev_customers, ext_customers):
        raise ValueError("development and external customer IDs do not match")
    customer_n = len(dev_customers)
    if customer_n != 300:
        raise ValueError(f"expected 300 customers, got {customer_n}")
    strict = np.load(STRICT_NPZ, allow_pickle=False)
    strict_dates = strict["dates"].astype(str)
    # The external NPZ retains three non-contiguous blocks.  Select by date,
    # not by accidental row order, so the sample remains reproducible.
    wanted_dates = strict_dates[np.asarray(days, dtype=int)]
    ext_lookup = {str(pd.Timestamp(d).date()): i for i, d in enumerate(ext_dates)}
    ext_idx = np.array([ext_lookup[str(d)] for d in wanted_dates], dtype=int)
    # Development normalization uses the earliest 219 complete dates, matching
    # the fixed train bank and its published customer grouping convention.
    dev_complete = np.flatnonzero(dev_valid.all(axis=0))
    train_idx = dev_complete[:219]
    out_rows: list[dict[str, object]] = []
    maps: dict[str, dict[str, object]] = {}
    # Include the published grouping and two alternatives.  For the published
    # mapping, IDs come from the frozen profile-bank manifest.
    manifest = json.loads((ROOT / "data/processed/ausgrid_profile_bank_v2_manifest.json").read_text())
    fixed = [np.asarray(group, dtype=int) - 1 for group in manifest["customer_group_mapping"]]
    map_specs: list[tuple[str, list[np.ndarray], int | None]] = [("frozen_seed_20261003", fixed, 20261003)]
    for seed in seeds:
        rng = np.random.default_rng(int(seed))
        perm = rng.permutation(customer_n)
        mapping = [np.asarray(x, dtype=int) for x in np.array_split(perm, 10)]
        map_specs.append((f"alternate_seed_{seed}", mapping, int(seed)))
    sites = ("611.3", "634.1")
    for name, mapping, seed in map_specs:
        maps[name] = {
            "seed": seed,
            "n_groups": len(mapping),
            "group_sizes": [int(len(x)) for x in mapping],
            "mapping_sha256": hashlib.sha256(np.concatenate(mapping).astype("<i8").tobytes()).hexdigest(),
        }
        dev_train_l, dev_train_p = _group_profiles(dev_load, dev_pv, mapping, train_idx)
        load_scale = np.maximum(dev_train_l.max(axis=(0, 1)), 1e-12)
        pv_scale = np.maximum(dev_train_p.max(axis=(0, 1)), 1e-12)
        ext_l, ext_p = _group_profiles(ext_load, ext_pv, mapping, ext_idx)
        emb_l = np.clip(exp.LOAD_OFFSET + exp.LOAD_GAIN * ext_l / load_scale[None, None, :], 0.35, 0.85)
        emb_p = np.clip(exp.PV_OFFSET + exp.PV_GAIN * ext_p / pv_scale[None, None, :], 0.0, 1.0)
        for site in sites:
            feeder = ACSnapshotFeeder(
                exp.FEEDER_PATH,
                battery_sites=(site,),
                pv_sites={"675.1": exp.PV_RATED_KW},
                voltage_limits=exp.VOLTAGE_LIMITS,
                line_loading_limit=exp.LINE_LIMIT,
                constraint_tolerance=1e-6,
            )
            for di, day in enumerate(days):
                for group in groups:
                    ld = emb_l[di, :, group]
                    pv = emb_p[di, :, group]
                    charge, export, reasons = protocol._bounds(feeder, ld, pv, site)
                    result = _dispatch(np.asarray(charge), np.asarray(export), ld)
                    out_rows.append({
                        "mapping": name,
                        "seed": -1 if seed is None else int(seed),
                        "site": site,
                        "date": str(wanted_dates[di]),
                        "day_index": int(day),
                        "group": int(group),
                        "baseline_reason_count": int(len(reasons)),
                        "planner_feasible": int(result.feasible),
                        "service_endpoint_kw": float(result.service_kw),
                    })
    rows = pd.DataFrame(out_rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows.to_csv(out_dir / "mapping_sensitivity_rows.csv", index=False)
    summary = rows.groupby(["mapping", "site"], as_index=False).agg(
        n=("service_endpoint_kw", "size"),
        mean_endpoint_kw=("service_endpoint_kw", "mean"),
        p05_endpoint_kw=("service_endpoint_kw", lambda x: float(x.quantile(0.05))),
        p95_endpoint_kw=("service_endpoint_kw", lambda x: float(x.quantile(0.95))),
        baseline_failures=("baseline_reason_count", lambda x: int((x > 0).sum())),
        planner_failures=("planner_feasible", lambda x: int((x == 0).sum())),
    )
    summary.to_csv(out_dir / "mapping_sensitivity_summary.csv", index=False)
    metadata = {
        "status": "customer_group_mapping_sensitivity_round1",
        "dev_source": str(DEV_CSV.relative_to(ROOT)),
        "external_source": str(EXT_CSV.relative_to(ROOT)),
        "dev_source_sha256": _sha256(DEV_CSV),
        "external_source_sha256": _sha256(EXT_CSV),
        "mappings": maps,
        "sample_days": [int(x) for x in days],
        "sample_dates": [str(x) for x in wanted_dates],
        "sample_groups": [int(x) for x in groups],
        "sites": list(sites),
        "normalization": "recomputed from the same mapping on the earliest 219 complete development dates only",
        "claim_boundary": "sample scalar-bound/AC-snapshot diagnostic; not the full external endpoint and no phase allocation is inferred",
        "rows": int(len(rows)),
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (out_dir / "README.md").write_text(
        "# Customer-group mapping sensitivity round 1\n\n"
        "This diagnostic reconstructs customer-level load/PV profiles from the public "
        "Ausgrid CSV extracts, then evaluates the frozen grouping and two alternate "
        "deterministic 30-customer groupings on three retained dates, one group and "
        "two primary sites. Normalization is recomputed from development dates only. "
        "The output is a sample sensitivity, not a new headline result or a calibrated "
        "customer-to-bus/phase allocation experiment.\n"
    )
    print(summary.to_string(index=False))
    return metadata


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=ROOT / "results/group_mapping_sensitivity_round1")
    ap.add_argument("--seeds", type=str, default="20261004,20261005")
    ap.add_argument("--days", type=str, default="0,102,218")
    ap.add_argument("--groups", type=str, default="0")
    args = ap.parse_args()
    seeds = tuple(int(x) for x in args.seeds.split(",") if x.strip())
    days = tuple(int(x) for x in args.days.split(",") if x.strip())
    groups = tuple(int(x) for x in args.groups.split(",") if x.strip())
    print(json.dumps(run(out_dir=args.out_dir, seeds=seeds, days=days, groups=groups), indent=2))


if __name__ == "__main__":
    main()
