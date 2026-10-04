"""Diagnose the IEEE-123 static snapshot operating point.

This is an independent diagnostic, not a transfer experiment.  It keeps the
declared 0.95--1.05 pu and 1.0 loading limits fixed and records every
intervention explicitly.  The purpose is to distinguish a physical feeder
limit from the operating-point state inherited by the snapshot adapter.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from recoveryflex.ac_snapshot import ACSnapshotFeeder


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "data/raw/ieee123_snapshot/master.dss"
LIMITS = {"vmin": 0.95, "vmax": 1.05, "line_ratio": 1.0, "transformer_ratio": 1.0}
SCALES = (0.50, 0.75, 1.00)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _feeder() -> ACSnapshotFeeder:
    # A zero-command battery is included only to match the experiment
    # adapter's compiled circuit.  It has no power injection in this audit.
    return ACSnapshotFeeder(
        MASTER,
        battery_sites=("47.1",),
        voltage_limits=(LIMITS["vmin"], LIMITS["vmax"]),
        line_loading_limit=LIMITS["line_ratio"],
        transformer_loading_limit=LIMITS["transformer_ratio"],
    )


def _set_neutral_regulator_taps(feeder: ACSnapshotFeeder) -> list[str]:
    d = feeder.dss
    changed: list[str] = []
    for name in d.Transformers.AllNames():
        if str(name).lower().startswith("reg"):
            d.Transformers.Name(name)
            d.Transformers.Wdg(2)
            d.Transformers.Tap(1.0)
            changed.append(str(name))
    d.Text.Command("set controlmode=off")
    return changed


def _disable_all_capacitors(feeder: ACSnapshotFeeder) -> list[str]:
    d = feeder.dss
    disabled: list[str] = []
    for name in d.Capacitors.AllNames():
        name = str(name)
        d.Circuit.Disable(f"capacitor.{name}")
        disabled.append(name)
    return disabled


def _state(feeder: ACSnapshotFeeder) -> dict[str, Any]:
    d = feeder.dss
    regs: list[dict[str, Any]] = []
    for raw in d.RegControls.AllNames():
        name = str(raw)
        d.RegControls.Name(name)
        transformer = str(d.RegControls.Transformer())
        tap_number = int(d.RegControls.TapNumber())
        tap = float("nan")
        if transformer:
            d.Transformers.Name(transformer)
            d.Transformers.Wdg(2)
            tap = float(d.Transformers.Tap())
        regs.append({"control": name, "transformer": transformer, "tap_number": tap_number, "tap": tap})
    caps: list[dict[str, Any]] = []
    for raw in d.Capacitors.AllNames():
        name = str(raw)
        d.Capacitors.Name(name)
        caps.append({"name": name, "states": [int(x) for x in d.Capacitors.States()], "kvar": float(d.Capacitors.kvar())})
    return {"regulators": regs, "capacitors": caps}


def _metrics(feeder: ACSnapshotFeeder) -> dict[str, Any]:
    volts = feeder._all_voltages()
    ratios = feeder._line_ratios()
    finite_v = [float(x) for x in volts.values() if math.isfinite(float(x))]
    finite_ratio = [(str(k), float(v)) for k, v in ratios.items() if math.isfinite(float(v))]
    line_items = [(k, v) for k, v in finite_ratio if k.startswith("line.")]
    xfmr_items = [(k, v) for k, v in finite_ratio if k.startswith("transformer.") and ".wdg" not in k]
    max_line_key, max_line = max(line_items, key=lambda kv: kv[1]) if line_items else ("", float("nan"))
    max_xfmr_key, max_xfmr = max(xfmr_items, key=lambda kv: kv[1]) if xfmr_items else ("", float("nan"))
    reasons: list[str] = []
    if finite_v and min(finite_v) < LIMITS["vmin"]:
        reasons.append("voltage_lower")
    if finite_v and max(finite_v) > LIMITS["vmax"]:
        reasons.append("voltage_upper")
    if math.isfinite(max_line) and max_line > LIMITS["line_ratio"]:
        reasons.append("line_loading")
    if math.isfinite(max_xfmr) and max_xfmr > LIMITS["transformer_ratio"]:
        reasons.append("transformer_loading")
    # l115 and sw1 are intentionally reported separately: sw1 is a short
    # parallel measurement point, while l115 is the feeder source line.
    l115 = float(ratios.get("line.l115", float("nan")))
    l115_amp = 400.0 * l115 if math.isfinite(l115) else float("nan")
    return {
        "converged": bool(feeder.dss.Solution.Converged()),
        "vmin_pu": min(finite_v) if finite_v else float("nan"),
        "vmax_pu": max(finite_v) if finite_v else float("nan"),
        "max_line_ratio": max_line,
        "max_line_component": max_line_key,
        "max_transformer_ratio": max_xfmr,
        "max_transformer_component": max_xfmr_key,
        "l115_ratio": l115,
        "l115_current_A_at_default_400A": l115_amp,
        "loss_kw": float(feeder.dss.Circuit.Losses()[0]) / 1000.0,
        "failure_reasons": reasons,
        "feasible_under_declared_limits": bool(not reasons and feeder.dss.Solution.Converged()),
        "state": _state(feeder),
    }


def _held_case(name: str, interventions: list[str], scale: float) -> dict[str, Any]:
    feeder = _feeder()
    applied: dict[str, Any] = {}
    if "neutral_regulator_taps" in interventions:
        applied["neutral_regulators"] = _set_neutral_regulator_taps(feeder)
    if "disable_capacitors" in interventions:
        applied["disabled_capacitors"] = _disable_all_capacitors(feeder)
    audit = feeder.solve(scale, 0.0, {"47.1": 0.0})
    result = _metrics(feeder)
    result.update({"case": name, "mode": "held_control_snapshot", "load_scale": scale, "interventions": interventions, "applied": applied})
    # Cross-check the adapter's returned telemetry.  The diagnostic keeps the
    # raw measurement in the result to make disagreements visible.
    result["adapter_failure_reasons"] = list(audit.failure_reasons)
    result["adapter_vmin_pu"] = audit.vmin
    result["adapter_vmax_pu"] = audit.vmax
    result["adapter_max_line_ratio"] = audit.max_line_loading
    return result


def _controlled_neutral_case(scale: float) -> dict[str, Any]:
    feeder = _feeder()
    changed = _set_neutral_regulator_taps(feeder)
    feeder._set_native_load_scale(scale)
    feeder.dss.Text.Command("set controlmode=static")
    feeder.dss.Solution.Solve()
    result = _metrics(feeder)
    result.update({"case": "controls_enabled_neutral_start", "mode": "controls_enabled", "load_scale": scale, "interventions": ["neutral_regulator_taps", "solve_with_static_controls"], "applied": {"neutral_regulators": changed}})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=ROOT / "results/ieee123_diagnostic_v6")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    cases = [
        ("adapter_held_state", []),
        ("neutral_regulator_taps", ["neutral_regulator_taps"]),
        ("capacitors_disabled", ["disable_capacitors"]),
        ("neutral_taps_and_capacitors_disabled", ["neutral_regulator_taps", "disable_capacitors"]),
    ]
    for name, interventions in cases:
        for scale in SCALES:
            rows.append(_held_case(name, interventions, scale))
    for scale in SCALES:
        rows.append(_controlled_neutral_case(scale))

    metadata = {
        "script": Path(__file__).name,
        "master": str(MASTER.relative_to(ROOT)),
        "master_sha256": _sha256(MASTER),
        "limits": LIMITS,
        "scales": list(SCALES),
        "battery_site": "47.1",
        "battery_command_kw": 0.0,
        "note": "Diagnostic only; no row was filtered for feasibility and no declared limit was changed.",
    }
    (args.out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    (args.out_dir / "raw_records.json").write_text(json.dumps(rows, indent=2, allow_nan=True) + "\n")
    fields = [
        "case", "mode", "load_scale", "converged", "vmin_pu", "vmax_pu", "max_line_ratio", "max_line_component",
        "max_transformer_ratio", "max_transformer_component", "l115_ratio", "l115_current_A_at_default_400A", "loss_kw",
        "failure_reasons", "feasible_under_declared_limits", "adapter_failure_reasons", "adapter_vmin_pu", "adapter_vmax_pu", "adapter_max_line_ratio", "interventions", "applied",
    ]
    with (args.out_dir / "summary.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            out = {k: row.get(k) for k in fields}
            out["failure_reasons"] = ";".join(row.get("failure_reasons", []))
            out["adapter_failure_reasons"] = ";".join(row.get("adapter_failure_reasons", []))
            out["interventions"] = ",".join(row.get("interventions", []))
            out["applied"] = json.dumps(row.get("applied", {}), sort_keys=True)
            w.writerow(out)
    print(f"wrote {len(rows)} records to {args.out_dir}")


if __name__ == "__main__":
    main()
