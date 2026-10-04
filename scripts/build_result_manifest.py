#!/usr/bin/env python3
"""Write a hash manifest for a frozen result directory and its figures."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", type=Path, required=True)
    ap.add_argument("--figures-dir", type=Path, required=True)
    ap.add_argument("--source-manifest", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    files = {}
    for root in (a.results_dir, a.figures_dir):
        for p in root.rglob("*"):
            # Chunk directories are intermediate parallel-run artifacts. The
            # previous exact-membership test missed them because their path
            # components are names such as ``chunk_0000_0055``.
            in_chunk = any(part.startswith("chunk_") for part in p.parts)
            if p.is_file() and p.name != a.out.name and p.name != "failure_records.csv" and not in_chunk:
                files[str(p.resolve())] = sha256(p)
    files[str(a.source_manifest.resolve())] = sha256(a.source_manifest)
    payload = {
        "status": "frozen_development_result_manifest_v4",
        "results_dir": str(a.results_dir.resolve()),
        "figures_dir": str(a.figures_dir.resolve()),
        "source_manifest": str(a.source_manifest.resolve()),
        # Keep the profile-to-feeder operating point beside the hashes.  This
        # is part of the numerical protocol, not a hidden implementation
        # default: the profile bank is normalized with train-only maxima,
        # every native load is scaled globally, and the fixed-PV/battery
        # surrogates are active-power-only with controls held off.
        "operating_point_embedding": {
            "normalization": "earliest-60-percent train split (2010-07-01 to 2011-02-04) group maxima over all 48 half-hour intervals",
            "profile_normalization": "train_only_maximum_per_group_and_channel",
            "load_offset": 0.40,
            "load_gain": 0.30,
            "load_clip": [0.35, 0.85],
            "pv_offset": 0.10,
            "pv_gain": 0.60,
            "pv_clip": [0.0, 1.0],
            "pv_rated_kw": 300.0,
            "pv_site": "675.1",
            "global_native_load_scale": True,
            "native_load_scales_kvar_with_kw": True,
            "controls_off": True,
            "battery_reactive_power_kvar": 0.0,
            "calibration_status": "synthetic_stress_embedding_not_customer_to_bus_calibration",
            "load_scale": {
                "formula": "clip(0.40 + 0.30 * load_kw / train_load_scale_kw, 0.35, 0.85)",
                "offset": 0.40,
                "gain": 0.30,
                "clip": [0.35, 0.85],
                "scope": "all_native_feeder_loads_P_and_Q",
            },
            "pv": {
                "bus_phase": "675.1",
                "rated_kw": 300.0,
                "formula": "P=-300 * clip(0.10 + 0.60 * pv_kw / train_pv_scale_kw, 0, 1)",
                "q_kvar": 0.0,
            },
            "battery": {
                "sites": ["611.3", "634.1"],
                "q_kvar": 0.0,
                "model": "constant_PQ_active_power_surrogate",
            },
            "controls": "off",
            "pcc_import_cap": None,
        },
        "files": dict(sorted(files.items())),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    print(json.dumps({"n_files": len(files), "out": str(a.out)}, indent=2))

if __name__ == "__main__":
    main()
