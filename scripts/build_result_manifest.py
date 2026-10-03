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
            if p.is_file() and p.name != a.out.name and p.name != "failure_records.csv" and "chunk_" not in p.parts:
                files[str(p.resolve())] = sha256(p)
    files[str(a.source_manifest.resolve())] = sha256(a.source_manifest)
    payload = {
        "status": "frozen_development_result_manifest_v3",
        "results_dir": str(a.results_dir.resolve()),
        "figures_dir": str(a.figures_dir.resolve()),
        "source_manifest": str(a.source_manifest.resolve()),
        "files": dict(sorted(files.items())),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(payload, indent=2))
    print(json.dumps({"n_files": len(files), "out": str(a.out)}, indent=2))

if __name__ == "__main__":
    main()
