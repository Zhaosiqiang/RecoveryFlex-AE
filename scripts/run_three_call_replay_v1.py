#!/usr/bin/env python3
"""Replay the predeclared three-call primary cell through OpenDSS.

Primary cell: E=500 kWh, second call [24,28), third call [32,36), exact
terminal SOC, and recovery in [12,24), [28,32), and [36,48). The scalar
endpoint is read from the completed three-call grid; this script only adds
the nonlinear interval replay audit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from recoveryflex.ac_snapshot import ACSnapshotFeeder  # noqa: E402
from recoveryflex.dispatch import plan_service  # noqa: E402
import run_corrected_experiment as exp  # noqa: E402
from recoveryflex.profile_bank import load_bank  # noqa: E402
from run_network_recovery_v2 import _embedded_external, _replay, AC_CONSTRAINT_TOLERANCE  # noqa: E402

SITES = ("611.3", "634.1")
SERVICES = ((8, 12), (24, 28), (32, 36))
RECOVERY = ((12, 24), (28, 32), (36, 48))
E_KWH = 500.0
SECOND_START = 24


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def protocol_spec() -> dict[str, object]:
    """Canonical specification for the replayed primary grid cell."""
    return {
        "service_windows": [list(x) for x in SERVICES],
        "recovery_windows": [list(x) for x in RECOVERY],
        "capacity_kwh": E_KWH,
        "terminal_mode": "exact",
        "terminal_visibility": "always",
        "initial_soc": exp.SOC_INITIAL,
        "terminal_soc": exp.SOC_INITIAL,
        "soc_bounds": [exp.SOC_RESERVE, 1.0],
        "efficiencies": [exp.ETA_CHARGE, exp.ETA_DISCHARGE],
        "dt_h": exp.DT_H,
        "sites": list(SITES),
    }


def protocol_sha256(spec: dict[str, object]) -> str:
    payload = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _failure_class(audits: list[object]) -> str:
    reasons: set[str] = set()
    for audit in audits:
        if not audit.feasible:
            reasons.update(str(x) for x in audit.failure_reasons)
            if not audit.converged:
                reasons.add("nonconverged")
    if not reasons:
        return "replay_feasibility_false"
    if any("voltage" in x.lower() for x in reasons):
        return "replay_voltage"
    if any("transformer" in x.lower() or "line" in x.lower() or "loading" in x.lower() for x in reasons):
        return "replay_loading"
    if "nonconverged" in reasons:
        return "replay_nonconvergence"
    return "replay_other"


def _load_bounds(path: Path, site: str) -> dict[tuple[int, int], tuple[np.ndarray, np.ndarray]]:
    frame = pd.read_csv(path)
    frame["site"] = frame.site.astype(str)
    frame = frame[frame.site == str(site)]
    out: dict[tuple[int, int], tuple[np.ndarray, np.ndarray]] = {}
    for (day, group), grouped in frame.groupby(["day_index", "group"], sort=False):
        grouped = grouped.sort_values("interval")
        if len(grouped) != 48:
            raise ValueError(f"expected 48 bound rows for {site}/{day}/{group}")
        out[(int(day), int(group))] = (grouped.charge_limit_kw.to_numpy(float), grouped.export_limit_kw.to_numpy(float))
    return out


def _worker(site: str, day_start: int, day_end: int, bounds_path: Path, rows_path: Path, source_path: Path) -> pd.DataFrame:
    selected = pd.read_csv(rows_path)
    selected["site"] = selected.site.astype(str)
    selected = selected[(selected.site == str(site)) & (selected.capacity_kwh == E_KWH) & (selected.second_start == SECOND_START)].copy()
    selected["day_index"] = selected.day_index.astype(int)
    selected = selected[(selected.day_index >= day_start) & (selected.day_index < day_end)]
    bounds = _load_bounds(bounds_path, site)
    bank = load_bank(exp.BANK_PATH)
    load, pv, _dates = _embedded_external(bank, source_path)
    feeder = ACSnapshotFeeder(exp.FEEDER_PATH, battery_sites=(str(site),), pv_sites={"675.1": exp.PV_RATED_KW}, voltage_limits=exp.VOLTAGE_LIMITS, line_loading_limit=exp.LINE_LIMIT, constraint_tolerance=AC_CONSTRAINT_TOLERANCE)
    records: list[dict[str, object]] = []
    for row in selected.sort_values(["day_index", "group"]).itertuples(index=False):
        day, group = int(row.day_index), int(row.group)
        charge, export = bounds[(day, group)]
        result = plan_service(charge, export, load[day, :48, group], SERVICES, recovery_windows=RECOVERY, energy_kwh=E_KWH, initial_soc=exp.SOC_INITIAL, terminal_soc_target=exp.SOC_INITIAL, soc_min=exp.SOC_RESERVE, soc_max=1.0, eta_charge=exp.ETA_CHARGE, eta_discharge=exp.ETA_DISCHARGE, dt_h=exp.DT_H, terminal_mode="exact", mode="network_lp", service_power_kw=float(row.service_power_lp_kw))
        if result.feasible:
            replay_ok, audits = _replay(feeder, load[day, :48, group], pv[day, :48, group], str(site), result)
            replay_class = "pass" if replay_ok else _failure_class(audits)
            max_v = max((float(a.vmax) for a in audits if np.isfinite(a.vmax)), default=float("nan"))
            max_loading = max((float(a.max_line_loading) for a in audits if np.isfinite(a.max_line_loading)), default=float("nan"))
            max_xfm = max((float(a.max_transformer_loading) for a in audits if np.isfinite(a.max_transformer_loading)), default=float("nan"))
        else:
            replay_ok, replay_class, max_v, max_loading, max_xfm = False, "planner_infeasible", float("nan"), float("nan"), float("nan")
        records.append({"date": str(row.date), "day_index": day, "group": group, "site": str(site), "capacity_kwh": E_KWH, "second_start": SECOND_START, "service_kw": float(row.service_power_lp_kw), "planner_feasible": int(result.feasible), "replay_feasible": int(replay_ok), "joint_success": int(result.feasible and replay_ok), "failure_class": replay_class, "terminal_soc": float(result.terminal_soc), "max_vmax": max_v, "max_line_loading": max_loading, "max_transformer_loading": max_xfm})
    return pd.DataFrame(records)


def _run_chunk_subprocess(site: str, start: int, stop: int, bounds_path: Path, rows_path: Path, source_path: Path, chunk_path: Path) -> Path:
    command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--site", site, "--day-start", str(start), "--day-end", str(stop), "--bounds", str(bounds_path), "--rows", str(rows_path), "--source", str(source_path), "--chunk-out", str(chunk_path)]
    subprocess.run(command, check=True, capture_output=True, text=True)
    return chunk_path


def run(bounds_path: Path, rows_path: Path, source_path: Path, out_dir: Path, workers: int) -> dict[str, object]:
    rows = pd.read_csv(rows_path)
    days = sorted(rows[(rows.capacity_kwh == E_KWH) & (rows.second_start == SECOND_START)].day_index.astype(int).unique())
    n_chunks = max(1, min(int(workers), len(days)))
    edges = [round(i * len(days) / n_chunks) for i in range(n_chunks + 1)]
    chunks = [(days[edges[i]], days[edges[i + 1] - 1] + 1) for i in range(n_chunks)]
    out_dir.mkdir(parents=True, exist_ok=True)
    pieces: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=n_chunks) as pool:
        futures = [pool.submit(_run_chunk_subprocess, site, start, stop, bounds_path, rows_path, source_path, out_dir / f"chunk_{site}_{start:04d}_{stop:04d}.csv") for site in SITES for start, stop in chunks]
        for future in as_completed(futures):
            pieces.append(pd.read_csv(future.result()))
    detail = pd.concat(pieces, ignore_index=True).sort_values(["site", "day_index", "group"]).reset_index(drop=True)
    detail.to_csv(out_dir / "three_call_replay_rows.csv", index=False)
    summary = detail.groupby("site", as_index=False).agg(n=("service_kw", "size"), planner_feasible=("planner_feasible", "sum"), replay_feasible=("replay_feasible", "sum"), joint_success=("joint_success", "sum"), mean_service_kw=("service_kw", "mean"))
    failures = detail[detail.failure_class != "pass"].groupby(["site", "failure_class"], as_index=False).size()
    summary.to_csv(out_dir / "three_call_replay_summary.csv", index=False)
    failures.to_csv(out_dir / "three_call_replay_failures.csv", index=False)
    spec = protocol_spec()
    grid_metadata_path = rows_path.parent / "metadata.json"
    grid_metadata = json.loads(grid_metadata_path.read_text(encoding="utf-8")) if grid_metadata_path.is_file() else {}
    metadata = {"status": "three_call_primary_replay_v1", "protocol": spec, "protocol_sha256": protocol_sha256(spec), "grid_protocol_sha256": grid_metadata.get("protocol_sha256"), "source_rows": str(rows_path), "bounds": str(bounds_path), "source_profile": str(source_path), "source_hashes": {"source_rows": sha256(rows_path), "bounds": sha256(bounds_path), "profile": sha256(source_path), "grid_metadata": sha256(grid_metadata_path) if grid_metadata_path.is_file() else None}, "ac_audit": {"constraint_tolerance": float(AC_CONSTRAINT_TOLERANCE), "voltage_limits": list(exp.VOLTAGE_LIMITS), "line_loading_limit": float(exp.LINE_LIMIT), "transformer_loading_limit": float(exp.LINE_LIMIT), "failure_edge_note": "A readback just above 1.0+1e-6 is retained as a replay_loading failure rather than silently rounded."}, "summary": summary.to_dict(orient="records"), "failure_classes": failures.to_dict(orient="records"), "files": ["three_call_replay_rows.csv", "three_call_replay_summary.csv", "three_call_replay_failures.csv", "metadata.json"]}
    metadata["script_sha256"] = sha256(Path(__file__).resolve())
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--bounds", type=Path, default=ROOT / "results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv")
    parser.add_argument("--rows", type=Path, default=ROOT / "results/three_call_grid_v1/three_call_rows.csv")
    parser.add_argument("--source", type=Path, default=ROOT / "data/processed/ausgrid_external_2012_2013_strict.npz")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/three_call_replay_v1")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--site", type=str, default=None)
    parser.add_argument("--day-start", type=int, default=None)
    parser.add_argument("--day-end", type=int, default=None)
    parser.add_argument("--chunk-out", type=Path, default=None)
    args = parser.parse_args()
    if args.worker:
        if args.site is None or args.day_start is None or args.day_end is None or args.chunk_out is None:
            raise SystemExit("worker mode requires --site, --day-start, --day-end, and --chunk-out")
        _worker(args.site, args.day_start, args.day_end, args.bounds, args.rows, args.source).to_csv(args.chunk_out, index=False)
    else:
        print(json.dumps(run(args.bounds, args.rows, args.source, args.out_dir, args.workers), indent=2))
