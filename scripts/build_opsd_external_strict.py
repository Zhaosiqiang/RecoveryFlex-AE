#!/usr/bin/env python3
"""Create a frozen 30-minute OPSD external-test profile for the same contract.

The public OPSD source is stored as one household pair at 15-minute native
resolution.  This adapter averages adjacent 15-minute kW values into the
48 half-hour positions used by the IEEE-13 contract.  Train-only scales are
still taken from the full OPSD bank; only the latest chronological test dates
are written to the external source file.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BANK = ROOT / "data/processed/opsd_profile_bank_v2.npz"
DEFAULT_OUT = ROOT / "data/processed/opsd_external_15to30_strict.npz"


def build(bank_path: Path = DEFAULT_BANK, out_path: Path = DEFAULT_OUT) -> dict[str, object]:
    x = np.load(bank_path, allow_pickle=False)
    load = np.asarray(x["load_kw"], dtype=float)
    pv = np.asarray(x["pv_kw"], dtype=float)
    if load.ndim != 2 or load.shape[1] != 96 or pv.shape != load.shape:
        raise ValueError(f"expected OPSD arrays with shape (day, 96), got {load.shape} and {pv.shape}")
    if "split" not in x.files or "dates" not in x.files:
        raise ValueError("OPSD bank must contain dates and split labels")
    split = np.asarray(x["split"]).astype(str)
    dates = np.asarray(x["dates"]).astype(str)
    if len(split) != len(load) or len(dates) != len(load):
        raise ValueError("OPSD arrays and metadata have inconsistent day counts")
    test = split == "test"
    if not test.any():
        raise ValueError("OPSD bank has no chronological test dates")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        load_kw=load[test].reshape(-1, 48, 2).mean(axis=2)[:, None, :],
        pv_kw=pv[test].reshape(-1, 48, 2).mean(axis=2)[:, None, :],
        dates=dates[test],
        split=np.full(int(test.sum()), "test", dtype="U5"),
        group_ids=np.asarray(["opsd_single_household"], dtype="U32"),
    )
    return {
        "source_bank": str(bank_path),
        "output": str(out_path),
        "native_intervals": 96,
        "output_intervals": 48,
        "n_test_days": int(test.sum()),
        "first_test_date": str(dates[test][0]),
        "last_test_date": str(dates[test][-1]),
        "aggregation": "arithmetic mean of adjacent 15-minute average-kW values",
        "normalization_policy": "train-only scales from the full OPSD bank; no test day contributes to the scales",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank", type=Path, default=DEFAULT_BANK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    import json
    print(json.dumps(build(args.bank, args.out), indent=2))
