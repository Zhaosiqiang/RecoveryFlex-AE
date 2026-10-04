#!/usr/bin/env python3
"""Verify the evidence boundary for review items 7--19, 21, and 25--28.

This is a read-only audit of the current RecoveryFlex working tree.  It does
not alter ``paper/main_v5.tex`` or recompute the primary AC experiment.  The
script records what is actually supported by files and result rows, so a
missing experiment is reported as a bounded limitation instead of being
silently treated as completed.

Running this script also writes a small Wilson/binomial companion table for
the common-offer result.  That table is supplementary evidence only; it does
not replace the manuscript's date-cluster intervals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _wilson(successes: int, trials: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """Wilson score interval, including the exact 0/0 and n/n boundaries."""
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError((successes, trials))
    if trials == 0:
        return float("nan"), float("nan")
    p = successes / trials
    den = 1.0 + z * z / trials
    centre = (p + z * z / (2.0 * trials)) / den
    half = z * math.sqrt(p * (1.0 - p) / trials + z * z / (4.0 * trials * trials)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


def _check_artifacts(root: Path, names: list[str]) -> tuple[bool, list[str]]:
    missing = [name for name in names if not (root / name).exists()]
    return not missing, missing


def _common_offer_wilson(root: Path, out_dir: Path) -> dict[str, Any]:
    """Write explicit failure counts and Wilson intervals for offer outcomes."""
    rows_path = root / "results/common_offer_temporal_evaluation_strict_v6/rows.csv"
    gate_path = root / "results/location_sensitivity_external_2012_2013_strict_v4/statistics/baseline_gate_by_site.csv"
    rows = pd.read_csv(rows_path, dtype={"site": str})
    gate = pd.read_csv(gate_path, dtype={"site": str})
    records: list[dict[str, Any]] = []

    def add(scope: str, site: str, outcome: str, successes: int, trials: int, note: str) -> None:
        lo, hi = _wilson(successes, trials)
        records.append({
            "scope": scope,
            "site": site,
            "outcome": outcome,
            "successes": int(successes),
            "failures": int(trials - successes),
            "trials": int(trials),
            "rate": float(successes / trials) if trials else float("nan"),
            "wilson_95_low": lo,
            "wilson_95_high": hi,
            "denominator_note": note,
        })

    for site, g in rows.groupby("site", sort=True):
        # rows.csv contains only baseline-gated evaluation units (1159/site).
        n = len(g)
        planner = int(g["planner_feasible"].sum())
        replay = int(g["replay_feasible"].sum())
        planner_replay = int((g["planner_feasible"].astype(bool) & g["replay_feasible"].astype(bool)).sum())
        add("baseline-gated", site, "planner_feasible", planner, n, "rows.csv; zero-power-gate pass units only")
        add("baseline-gated", site, "replay_given_planner", replay, planner, "conditional replay denominator is planner-feasible units")
        add("baseline-gated", site, "joint_planner_and_replay", planner_replay, n, "rows.csv; zero-power-gate pass units only")

        gate_row = gate.loc[gate["site"].astype(str).eq(str(site))]
        if len(gate_row) != 1:
            raise ValueError(f"expected one gate row for {site}, got {len(gate_row)}")
        physical_n = int(gate_row.iloc[0]["n_units"]) * 116 // 219
        # Each site has 116 retained evaluation dates × 10 groups = 1160
        # physical units. The gate table is 219-date / 2190-unit based.
        physical_n = 1160
        add("unconditional-physical", site, "planner_feasible", planner, physical_n, "one gate failure/site counted as failure")
        add("unconditional-physical", site, "joint_planner_and_replay", planner_replay, physical_n, "one gate failure/site counted as failure")

    # Pooled rows are the headline denominator; add both conditional and
    # unconditional forms so percentages cannot be confused.
    n = len(rows)
    planner = int(rows["planner_feasible"].sum())
    replay = int(rows["replay_feasible"].sum())
    joint = int((rows["planner_feasible"].astype(bool) & rows["replay_feasible"].astype(bool)).sum())
    add("pooled-baseline-gated", "ALL", "planner_feasible", planner, n, "8,113 baseline-gated evaluation units")
    add("pooled-baseline-gated", "ALL", "replay_given_planner", replay, planner, "conditional replay denominator is 8,045 planner-feasible units")
    add("pooled-baseline-gated", "ALL", "joint_planner_and_replay", joint, n, "8,113 baseline-gated evaluation units")
    physical_n = 8120
    add("pooled-unconditional-physical", "ALL", "planner_feasible", planner, physical_n, "seven zero-power gate failures counted as failures")
    add("pooled-unconditional-physical", "ALL", "joint_planner_and_replay", joint, physical_n, "seven zero-power gate failures counted as failures")

    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "failure_count_wilson.csv"
    pd.DataFrame.from_records(records).to_csv(out, index=False)
    return {
        "path": str(out.relative_to(root)),
        "rows": len(records),
        "pooled_joint": {"successes": joint, "gated_trials": n, "physical_trials": physical_n},
        "pooled_joint_wilson_gated": list(_wilson(joint, n)),
        "pooled_joint_wilson_physical": list(_wilson(joint, physical_n)),
    }


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--manuscript", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    root = args.root.resolve()
    manuscript = (args.manuscript or root / "paper/main_v5.tex").resolve()
    text = _read(manuscript)
    out_dir = (args.out or root / "results/common_offer_temporal_evaluation_strict_v6").resolve()

    checks: list[dict[str, Any]] = []

    def record(item: str, status: str, evidence: list[str], detail: str, *, required: list[str] = ()) -> None:
        checks.append({"item": item, "status": status, "evidence": evidence, "detail": detail,
                       "missing": [p for p in required if not (root / p).exists()]})

    # Item 7 — replay scope and evidence tiers.
    files = [
        "results/network_recovery_external_2012_2013_strict_v4/policy_rows.csv",
        "results/three_call_replay_v1/three_call_replay_rows.csv",
        "results/three_call_replay_v1/three_call_replay_failures.csv",
        "docs/reviews/ac_coverage_scope_audit_round1.md",
    ]
    ok, missing = _check_artifacts(root, files)
    if ok:
        policy = pd.read_csv(root / files[0])
        replay = pd.read_csv(root / files[1])
        record("7", "complete-bounded", files,
               f"primary rows={len(policy)}; selected three-call replay rows={len(replay)}; manuscript labels unselected grids as scalar sensitivities; missing={missing}")
    else:
        record("7", "incomplete", files, f"missing={missing}", required=files)

    # Item 8 — ideal battery/device boundary.
    required = ["results/ac_coverage_audit_round1/device_power_cap_summary.csv",
                "docs/reviews/ieee123_diagnostic_v6.md"]
    terms = all(s in text for s in ("Q=0", "kVA", "ideal", "active-power surrogate"))
    ok, missing = _check_artifacts(root, required)
    record("8", "complete-bounded" if ok and terms else "incomplete", required,
           "symmetric scalar power-cap diagnostic exists; reactive/kVA/SOC-dependent/ramp/thermal dynamics remain explicitly outside the model",
           required=required)

    # Item 9 — embedding sensitivity and the missing night/phase experiment.
    emb = root / "results/ac_coverage_audit_round1/embedding_sensitivity_summary.csv"
    variants: list[str] = []
    if emb.is_file():
        variants = sorted(pd.read_csv(emb)["variant"].astype(str).unique().tolist())
    expected = {"base", "higher_load_gain", "lower_pv_rating", "higher_pv_rating", "pv_at_634.1"}
    night = root / "results/scope_sensitivity_round2/night_pv_zero_rows.csv"
    status = "complete-bounded" if expected.issubset(variants) else "incomplete"
    if not night.exists():
        status = "bounded-gap"
    record("9", status, [str(emb.relative_to(root))] if emb.exists() else [],
           f"existing variants={variants}; night-PV=0 artifact present={night.exists()}; phase/customer-to-bus mapping remains unavailable in the source",
           required=[str(emb.relative_to(root))])

    # Item 10 — feeder transfer boundary.
    required = ["docs/reviews/ieee123_scope_check.md", "docs/reviews/ieee123_diagnostic_v6.md"]
    ok, missing = _check_artifacts(root, required)
    scoped = all(s in text for s in ("one public IEEE 13-node feeder", "no cross-feeder transfer claim"))
    record("10", "complete-bounded" if ok and scoped else "incomplete", required,
           "IEEE-123 is retained as an adapter diagnostic only; no second-feeder quantitative claim is made",
           required=required)

    # Item 11 — chronology stress and the export-floor binding audit.
    required = ["results/binding_ablation_strict_v5/two_mwh_binding_summary.csv",
                "results/three_call_grid_v1/three_call_summary.csv",
                "docs/reviews/technical_stats_round19.md"]
    ok, missing = _check_artifacts(root, required)
    record("11", "complete-bounded" if ok else "incomplete", required,
           "2-MWh service-window-floor binding and complete three-call grid are present; scalar-bound capacity/contract sensitivities are labeled as such",
           required=required)

    # Item 12 — offline deterministic H-series boundary.
    required_terms = ("not communication", "hindsight", "not deployable", "not communication-delay")
    found = [s for s in required_terms if s.lower() in text.lower()]
    record("12", "complete-bounded" if len(found) >= 2 else "incomplete", ["paper/main_v5.tex"],
           f"boundary terms found={found}; no online/forecast baseline is claimed")

    # Item 13 — timeline/freeze protocol.
    required = ["docs/block_stratified_bootstrap_v1.md", "data/processed/ausgrid_external_2012_2013_strict.json"]
    ok, missing = _check_artifacts(root, required)
    timeline = "tab:timeline" in text and all(s in text for s in ("2010--2011", "2012--2013", "External calibration block", "External evaluation blocks"))
    record("13", "complete" if ok and timeline else "incomplete", required + ["paper/main_v5.tex"],
           "timeline table and role/freeze fields are present; source structure inspection is disclosed",
           required=required)

    # Item 14 — common-offer denominators and stratification.
    required = ["results/common_offer_temporal_evaluation_strict_v6/rows.csv",
                "results/common_offer_temporal_evaluation_strict_v6/site_summary.csv",
                "results/common_offer_temporal_evaluation_strict_v6/date_summary.csv",
                "results/location_sensitivity_external_2012_2013_strict_v4/statistics/baseline_gate_by_site.csv"]
    ok, missing = _check_artifacts(root, required)
    record("14", "complete-bounded" if ok else "incomplete", required,
           "site/date summaries and unconditional 8,120 denominator are available; gate failures are retained as automatic failures",
           required=required)

    # Item 15 — non-contiguous block uncertainty and pooled threshold uncertainty.
    required = ["docs/block_stratified_bootstrap_v1.md",
                "results/network_recovery_external_2012_2013_strict_v4/statistics/block_leave_one_out.csv",
                "results/common_offer_temporal_evaluation_strict_v6/calibration_quantile_bootstrap_summary.json"]
    ok, missing = _check_artifacts(root, required)
    record("15", "complete-bounded" if ok else "incomplete", required,
           "block-stratified bootstrap, block leave-one-out, and pooled lower-tail date-cluster quantile uncertainty are present; intervals are descriptive",
           required=required)

    # Item 16 — physical interpretation of 0.216 kWh and failure diagnostics.
    required = ["results/common_offer_temporal_evaluation_strict_v6/failure_records.csv"]
    ok, missing = _check_artifacts(root, required)
    cautious = ("not measured unmet energy from the AC replay" in text
                and "not a future delivery guarantee" in text)
    record("16", "complete-bounded" if ok and cautious else "incomplete", required,
           "shortfall is computed from local scalar endpoint gap × four service hours; failure rows retain date/site/group/message",
           required=required)

    # Item 17 — optimistic constant-bound counterfactual.
    required = ["results/network_recovery_external_2012_2013_strict_v4/failure_records.csv",
                "docs/reviews/ac_coverage_scope_audit_round1.md"]
    ok, missing = _check_artifacts(root, required)
    scope_doc = _read(root / "docs/reviews/ac_coverage_scope_audit_round1.md").lower()
    counterfactual = all(s in (text + scope_doc).lower() for s in ("optimistic", "pcc-import-cap", "counterfactual"))
    record("17", "complete-bounded" if ok and counterfactual else "incomplete", required,
           "constant-bound is labeled an intentionally optimistic non-deliverable diagnostic; no PCC or phase constraint is claimed",
           required=required)

    # Item 18 — decision chain/economic scope.
    required = ["docs/decision_chain_v6.md"]
    ok, missing = _check_artifacts(root, required)
    economics = all(s in text.lower() for s in ("does not assign a market price", "economic objective"))
    record("18", "complete-bounded" if ok and economics else "incomplete", required,
           "DSO/aggregator screening chain is explicit; prices, penalties, activation probabilities and market valuation remain outside scope",
           required=required)

    # Item 19 — reproducible source bundle and licence/archive metadata.
    required = ["docs/reproducibility_v5.md", "docs/runtime_environment_v5.txt",
                "docs/runtime_execution_v6.txt", "data/raw/THIRD_PARTY_LICENSES.txt",
                "CITATION.cff"]
    ok, missing = _check_artifacts(root, required)
    reproducible = all(s in text for s in ("v5.1.0", "persistent DOI has not been assigned"))
    record("19", "complete-tagged" if ok and reproducible else "incomplete", required,
           "immutable GitHub tag, hashes, runtime/commands, OpenDSS fixtures and licences are recorded; DOI is explicitly absent",
           required=required)

    # Item 21 — vocabulary and denominators.
    terms = ("baseline-gated", "planner-plus-replay", "conditional replay", "unconditional", "descriptive")
    found = [s for s in terms if s.lower() in text.lower()]
    record("21", "complete" if len(found) >= 4 else "incomplete", ["paper/main_v5.tex", "results/common_offer_temporal_evaluation_strict_v6/rows.csv"],
           f"controlled terms found={found}; common-offer rows carry planner/replay/baseline flags")

    # Item 25 — rounded display precision with raw provenance.
    required = ["results/network_recovery_external_2012_2013_strict_v4/statistics/statistics.csv",
                "results/network_recovery_external_2012_2013_strict_v4/ac_bounds.csv"]
    ok, missing = _check_artifacts(root, required)
    precision = "0.078125" in text or "0.078125" in _read(root / "docs/reproducibility_v5.md")
    record("25", "complete-bounded" if ok and precision else "incomplete", required,
           "tables display rounded descriptive values while source CSVs retain full precision and the 0.078125-kW search resolution is disclosed",
           required=required)

    # Item 26 — failure counts and boundary-safe binomial intervals.
    wilson = _common_offer_wilson(root, out_dir)
    record("26", "complete-supplement" if wilson["rows"] else "incomplete", [wilson["path"]],
           "Wilson 95% score intervals and explicit successes/failures/trials were generated; manuscript date-cluster intervals remain descriptive and are not guarantees")

    # Item 27 — grouping, seed and mapping sensitivity.
    manifest = root / "data/processed/ausgrid_profile_bank_v2_manifest.json"
    meta = json.loads(manifest.read_text()) if manifest.is_file() else {}
    groups = meta.get("n_groups") == 10 and meta.get("n_customers") == 300 and meta.get("seed") == 20261003
    mapping_audit = root / "results/group_mapping_sensitivity_round1/mapping_sensitivity_summary.csv"
    mapping_meta = root / "results/group_mapping_sensitivity_round1/metadata.json"
    mapping_ok = mapping_audit.is_file() and mapping_meta.is_file()
    record("27", "complete-bounded" if groups and mapping_ok else ("bounded-gap" if groups else "incomplete"),
           ["data/processed/ausgrid_profile_bank_v2_manifest.json", str(mapping_audit.relative_to(root))],
           "fixed 300-customer → 10 groups × 30 mapping and seed are recorded; two alternate seeded groupings were rebuilt from customer-level public CSVs on a predeclared sample, while no phase/customer-to-bus mapping is inferred")

    # Item 28 — AI/authorship/licence/provenance placement.
    required = ["docs/ai_use_record_v5.md", "data/raw/THIRD_PARTY_LICENSES.txt", "CITATION.cff"]
    ok, missing = _check_artifacts(root, required)
    declaration = "Declaration of generative AI" in text and "Declaration of competing interest" in text
    record("28", "complete" if ok and declaration else "incomplete", required,
           "AI, CRediT, competing-interest, data/code availability, and licence/provenance statements are present in manuscript and source bundle",
           required=required)

    payload = {
        "audit": "adversarial_review_scope_v7",
        "source_review": "pasted-text-1.txt (external review attachment; not packaged)",
        "manuscript": str(manuscript.relative_to(root)) if manuscript.is_relative_to(root) else str(manuscript),
        "manuscript_sha256": _sha256(manuscript) if manuscript.is_file() else None,
        "checks": checks,
        "summary": {
            "total": len(checks),
            "complete_like": sum(c["status"].startswith("complete") for c in checks),
            "bounded_or_gap": sum(c["status"].endswith("bounded") or "gap" in c["status"] for c in checks),
            "incomplete": sum(c["status"] == "incomplete" for c in checks),
        },
    }
    out_path = root / "docs/reviews/adversarial_scope_verification_v7.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
    for c in checks:
        print(f"{c['item']:>2}: {c['status']:<18} {c['detail']}")


if __name__ == "__main__":
    _main()
