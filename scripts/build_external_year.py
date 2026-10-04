#!/usr/bin/env python3
"""Build a strict held-out Ausgrid calendar-year profile bank.

The group mapping and normalization scales are frozen from the development
bank. A date is retained only when every customer has complete GC and GG
records and every customer that has a CL record anywhere in the external file
has a complete CL record on that date. Customers with no CL record in the
external file are structural zero controlled load. Group means are computed
after reindexing to all frozen customer IDs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HF_DATASET_URL = "https://huggingface.co/SolarSys2026/EnergyTrading/tree/2c72ed7c0b3628b0c5fd909da31771fcc5fd9a09/Dataset/Data/Ausgrid_raw_data"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def build(src: Path, out: Path) -> dict:
    manifest = json.loads((ROOT / "data/processed/ausgrid_profile_bank_v2_manifest.json").read_text())
    group_ids = [np.asarray(g, dtype=int) for g in manifest["customer_group_mapping"]]
    groups = [g - 1 for g in group_ids]
    customers = np.array(sorted({int(i) for g in group_ids for i in g}), dtype=int)
    raw = pd.read_csv(src, skiprows=[0])
    raw["date"] = pd.to_datetime(raw["date"], dayfirst=True, errors="coerce")
    raw["Customer"] = pd.to_numeric(raw["Customer"], errors="coerce").astype("Int64")
    tcols = [str(c) for c in raw.columns if ":" in str(c)]
    if len(tcols) != 48:
        raise ValueError(f"expected 48 intervals, got {len(tcols)}")
    for c in tcols:
        raw[c] = pd.to_numeric(raw[c], errors="coerce")
    raw = raw[raw.Customer.isin(customers) & raw.date.notna()]
    dates = pd.DatetimeIndex(sorted(raw["date"].unique()))
    base = pd.MultiIndex.from_product([customers, dates], names=["Customer", "date"])
    grouped = (
        raw[raw["Consumption Category"].isin(["GC", "CL", "GG"])]
        .groupby(["Customer", "date", "Consumption Category"], sort=True)[tcols]
        .mean()
    )
    arrays = {}
    present = {}
    for cat in ("GC", "CL", "GG"):
        if cat in grouped.index.get_level_values("Consumption Category"):
            frame = grouped.xs(cat, level="Consumption Category").reindex(base)
        else:
            frame = pd.DataFrame(index=base, columns=tcols, dtype=float)
        arrays[cat] = frame
        present[cat] = frame.notna().all(axis=1).to_numpy().reshape(len(customers), len(dates))
    cl_any = present["CL"].any(axis=1)
    valid = present["GC"] & present["GG"]
    valid &= (~cl_any[:, None]) | present["CL"]
    valid_dates = valid.all(axis=0)
    load = (
        arrays["GC"].fillna(0.0).to_numpy(float)
        + arrays["CL"].fillna(0.0).to_numpy(float)
    ).reshape(len(customers), len(dates), 48) / 0.5
    pv = arrays["GG"].fillna(0.0).to_numpy(float).reshape(len(customers), len(dates), 48) / 0.5
    out_load, out_pv, out_dates = [], [], []
    for j, date in enumerate(dates):
        if not valid_dates[j]:
            continue
        out_load.append(np.stack([load[g, j].mean(axis=0) for g in groups]))
        out_pv.append(np.stack([pv[g, j].mean(axis=0) for g in groups]))
        out_dates.append(date)
    load_out = np.asarray(out_load, float)
    pv_out = np.asarray(out_pv, float)
    date_out = pd.DatetimeIndex(out_dates)
    blocks = []
    if len(date_out):
        start = prev = date_out[0]
        for date in date_out[1:]:
            if date - prev != pd.Timedelta(days=1):
                blocks.append([str(start.date()), str(prev.date()), int((prev - start).days + 1)])
                start = date
            prev = date
        blocks.append([str(start.date()), str(prev.date()), int((prev - start).days + 1)])
    np.savez_compressed(
        out,
        load_kw=load_out,
        pv_kw=pv_out,
        dates=np.asarray(date_out.strftime("%Y-%m-%d"), dtype="U10"),
        group_ids=np.asarray(["-".join(map(str, g)) for g in groups], dtype="U120"),
    )
    meta = {
        "source": str(src),
        "source_sha256": sha256(src),
        "source_catalog_url": HF_DATASET_URL,
        "n_days_raw": int(len(dates)),
        "n_days": int(len(date_out)),
        "n_invalid_dates": int((~valid_dates).sum()),
        "n_customers": int(len(customers)),
        "n_groups": len(groups),
        "intervals_per_day": 48,
        "units": "average kW; source values are kWh per 30-minute interval",
        "channels": "load = fixed-denominator customer mean of GC + CL; pv = fixed-denominator customer mean of GG",
        "cl_rule": "CL absent for every date in this file is structural zero; any customer with a CL row must have a complete CL row on retained dates",
        "valid_date_rule": "all frozen customers have complete GC and GG; CL rule also passes",
        "groups_frozen_from": "ausgrid_profile_bank_v2_manifest.json",
        "date_range_raw": [str(dates.min().date()), str(dates.max().date())],
        "date_range_retained": [str(date_out.min().date()), str(date_out.max().date())] if len(date_out) else [],
        "retained_date_blocks": blocks,
        "retained_dates": [str(d.date()) for d in date_out],
        "customer_group_mapping": [list(map(int, g)) for g in group_ids],
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(build(args.source, args.out), indent=2))
