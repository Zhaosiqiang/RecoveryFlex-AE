#!/usr/bin/env python3
"""Run the fair-window external experiment in independent day chunks."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_network_recovery_v2.py"


def _run_chunk(start: int, stop: int, groups: int, source: Path, out: Path, sites: str,
               cached_bounds: Path | None = None, cached_audit: Path | None = None,
               normalizer_bank: Path | None = None) -> str:
    cmd = [
        sys.executable,
        str(SCRIPT),
        "--day-start",
        str(start),
        "--day-end",
        str(stop),
        "--groups",
        str(groups),
        "--source",
        str(source),
        "--out-dir",
        str(out),
        "--sites",
        sites,
    ]
    if cached_bounds is not None:
        cmd.extend(["--cached-bounds", str(cached_bounds)])
        if cached_audit is not None:
            cmd.extend(["--cached-audit", str(cached_audit)])
    if normalizer_bank is not None:
        cmd.extend(["--normalizer-bank", str(normalizer_bank)])
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    (out / "run_stdout.json").write_text(completed.stdout)
    return completed.stdout


def run(source: Path, out: Path, days: int, groups: int, workers: int, sites: str = "611.3,634.1",
        cached_bounds: Path | None = None, cached_audit: Path | None = None,
        normalizer_bank: Path | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    n_chunks = max(1, min(int(workers), int(days)))
    edges = [round(i * days / n_chunks) for i in range(n_chunks + 1)]
    chunks = [(edges[i], edges[i + 1]) for i in range(n_chunks)]
    with ThreadPoolExecutor(max_workers=n_chunks) as pool:
        futures = {
            pool.submit(
                _run_chunk,
                start,
                stop,
                groups,
                source,
                out / f"chunk_{start:04d}_{stop:04d}",
                sites,
                cached_bounds,
                cached_audit,
                normalizer_bank,
            ): (start, stop)
            for start, stop in chunks
        }
        for future in as_completed(futures):
            future.result()

    policy = []
    bounds = []
    traces = []
    for start, stop in chunks:
        chunk = out / f"chunk_{start:04d}_{stop:04d}"
        policy.append(pd.read_csv(chunk / "policy_rows.csv"))
        bounds.append(pd.read_csv(chunk / "ac_bounds.csv"))
        trace_path = chunk / "representative_trace.csv"
        if trace_path.exists():
            traces.append(pd.read_csv(trace_path))
    policy_df = pd.concat(policy, ignore_index=True).sort_values(["date", "group", "site", "method"])
    bounds_df = pd.concat(bounds, ignore_index=True).sort_values(["date", "group", "site", "interval"])
    policy_df.to_csv(out / "policy_rows.csv", index=False)
    bounds_df.to_csv(out / "ac_bounds.csv", index=False)
    if traces:
        traces[0].to_csv(out / "representative_trace.csv", index=False)
    grouped = policy_df.groupby(["site", "method"], as_index=False).agg(
        mean_service_kw=("service_kw", "mean"),
        replay_success=("replay_feasible", "mean"),
        baseline_success=("baseline_feasible", "mean"),
        n=("service_kw", "size"),
    )
    conditional = (
        policy_df[policy_df.baseline_feasible == 1]
        .groupby(["site", "method"], as_index=False)
        .agg(
            conditional_replay_success=("replay_feasible", "mean"),
            conditional_mean_service_kw=("service_kw", "mean"),
            n_baseline=("service_kw", "size"),
        )
    )
    summary = {
        "status": "network_recovery_v2_parallel",
        "source": str(source),
        "n_days": int(days),
        "n_groups": int(groups),
        "workers": int(n_chunks),
        "sites": [s for s in sites.split(",") if s],
        "summary": grouped.to_dict(orient="records"),
        "conditional_summary": conditional.to_dict(orient="records"),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/network_recovery_external_2012_2013_v2")
    parser.add_argument("--days", type=int, default=219)
    parser.add_argument("--groups", type=int, default=10)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sites", type=str, default="611.3,634.1")
    parser.add_argument("--cached-bounds", type=Path, default=None)
    parser.add_argument("--cached-audit", type=Path, default=None)
    parser.add_argument("--normalizer-bank", type=Path, default=None,
                        help="profile bank whose train split supplies normalization scales")
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.out_dir, args.days, args.groups, args.workers, args.sites,
                         args.cached_bounds, args.cached_audit, args.normalizer_bank), indent=2))
