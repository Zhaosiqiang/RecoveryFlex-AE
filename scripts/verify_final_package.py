#!/usr/bin/env python3
"""Verify a manuscript/result package without rerunning experiments.

The default target is the strict-v4 package. ``--version v3`` keeps the
earlier strict-v3 smoke checks available for the archived development package.
Checks read expected values from the declared CSV files and compare those
values with the manuscript, rather than embedding old v3 headline numbers in
the v4 path.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

RAW_REPRO_FILES = {
    "data/raw/README.md",
    "data/raw/feeder_manifest.json",
    "data/raw/THIRD_PARTY_LICENSES.txt",
    "data/raw/IEEE13Nodeckt.dss",
    "data/raw/IEEELineCodes.dss",
    "data/raw/IEEE13Node_BusXY.csv",
    "data/raw/ausgrid/README.md",
    "data/raw/ieee123_snapshot/manifest.json",
    "data/raw/ieee123_snapshot/master.dss",
    "data/raw/ieee123_snapshot/Buscoords.dss",
    "data/raw/ieee123_snapshot/IEEE123Loads.dss",
    "data/raw/ieee123_snapshot/IEEE123Regulators.dss",
    "data/raw/ieee123_snapshot/IEEELinecodes.dss",
    "data/raw/ieee123_qsts/manifest.json",
}

CONFIG = {
    "v4": {
        "manuscript": Path("paper/main_v4.tex"),
        "pdf": Path("paper/main_v4.pdf"),
        "figures": Path("paper/figures_v4"),
        "primary": Path("results/network_recovery_external_2012_2013_strict_v4"),
        "extras": [
            Path("results/capacity_sensitivity_strict_v4"),
            Path("results/causal_capacity_sensitivity_strict_v4"),
            Path("results/safe_offer_metrics_strict_v4"),
        ],
        "bundle": Path("submission_bundle_v4"),
        # The final result floats are intentionally flushed before the
        # declarations and references.
        "expected_pages": 12,
    },
    "v5": {
        "manuscript": Path("paper/main_v5.tex"),
        "pdf": Path("paper/main_v5.pdf"),
        "figures": Path("paper/figures_v5"),
        "primary": Path("results/network_recovery_external_2012_2013_strict_v4"),
        "extras": [
            Path("results/capacity_sensitivity_strict_v4"),
            Path("results/causal_capacity_sensitivity_strict_v4"),
            Path("results/safe_offer_metrics_strict_v4"),
            Path("results/headroom_margin_sensitivity_strict_v4"),
            Path("results/opsd_cross_source_strict_v5"),
            Path("results/common_offer_replay_strict_v5"),
            Path("results/binding_ablation_strict_v5"),
            Path("results/location_sensitivity_external_2012_2013_strict_v4"),
            Path("results/calendar_mechanism_audit_round1"),
            Path("results/common_offer_temporal_evaluation_strict_v6"),
            Path("results/common_offer_temporal_evaluation_capacity500_current"),
            Path("results/capacity_certificate_full_current"),
            Path("results/three_call_grid_v1"),
            Path("results/three_call_replay_v1"),
            Path("results/ac_coverage_audit_round1"),
        ],
        "bundle": Path("submission_bundle_v5"),
        # The current manuscript includes the full replay/uncertainty audit
        # paragraphs and the revised full-width trace.
        "expected_pages": 28,
    },
    "v3": {
        "manuscript": Path("paper/main_v3.tex"),
        "pdf": Path("paper/main_v3.pdf"),
        "figures": Path("figures/network_recovery_strict_v3"),
        "primary": Path("results/network_recovery_external_2012_2013_strict_v3"),
        "extras": [],
        "bundle": Path("submission_bundle"),
        "expected_pages": 11,
    },
}


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def resolve(relative: Path) -> Path:
    return (ROOT / relative).resolve()


def close(a: float, b: float, tolerance: float = 1e-3) -> bool:
    return abs(a - b) <= tolerance


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv(path: Path, failures: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        fail(f"missing CSV: {path}", failures)
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def row(rows: list[dict[str, str]], **selectors: object) -> dict[str, str] | None:
    for candidate in rows:
        if all(str(candidate.get(key, "")) == str(value) for key, value in selectors.items()):
            return candidate
    return None


def number_in_text(text: str, value: float, tolerance: float = 1.1e-3) -> bool:
    numbers = re.findall(r"(?<![A-Za-z])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)", text)
    return any(close(float(token.replace(",", "")), value, tolerance) for token in numbers)


def assert_number_from_row(
    text: str,
    candidate: dict[str, str] | None,
    label: str,
    failures: list[str],
) -> None:
    if candidate is None:
        fail(f"missing CSV row for {label}", failures)
        return
    try:
        value = float(candidate["estimate"])
    except (KeyError, TypeError, ValueError):
        fail(f"CSV row for {label} has no numeric estimate", failures)
        return
    if not number_in_text(text, value):
        fail(f"manuscript does not contain the CSV-derived value {value:.6f} for {label}", failures)


def check_pdf_pages(path: Path, expected: int, failures: list[str]) -> None:
    if not path.exists():
        fail(f"missing PDF: {path}", failures)
        return
    try:
        output = subprocess.check_output(["pdfinfo", str(path)], text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        fail(f"pdfinfo could not inspect {path}: {exc}", failures)
        return
    match = re.search(r"^Pages:\s+(\d+)", output, flags=re.MULTILINE)
    if not match or int(match.group(1)) != expected:
        actual = match.group(1) if match else "unknown"
        fail(f"{path} has {actual} pages; expected {expected}", failures)


def check_results_float_order(
    path: Path,
    failures: list[str],
    figure_numbers: tuple[int, ...] = (6, 7, 8),
) -> None:
    """Ensure late result figures precede Discussion and References."""
    if not path.exists():
        return
    try:
        text = subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        fail(f"pdftotext could not inspect figure order in {path}: {exc}", failures)
        return
    pages = text.split("\f")

    def first_page(pattern: str) -> int | None:
        compiled = re.compile(pattern, flags=re.MULTILINE)
        for index, page in enumerate(pages, start=1):
            if compiled.search(page):
                return index
        return None

    figure_pages = {
        number: first_page(rf"^\s*Figure\s+{number}:")
        for number in figure_numbers
    }
    discussion_page = first_page(r"^\s*4\s+Discussion\b")
    references_page = first_page(r"^\s*References\s*$")
    if discussion_page is None or references_page is None:
        fail(f"could not locate Discussion/References headings in {path}", failures)
        return
    for number, page in figure_pages.items():
        if page is None:
            fail(f"Figure {number} caption is missing from {path}", failures)
        elif not page < discussion_page < references_page:
            fail(
                f"Figure {number} is after Discussion or References in {path}: "
                f"figure={page}, discussion={discussion_page}, references={references_page}",
                failures,
            )


def inspect_json_for_absolute_paths(value: Any, where: str, failures: list[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str) and key.startswith("/"):
                fail(f"absolute JSON path key remains at {where}: {key}", failures)
            inspect_json_for_absolute_paths(item, where, failures)
    elif isinstance(value, list):
        for item in value:
            inspect_json_for_absolute_paths(item, where, failures)
    elif isinstance(value, str) and (
        value.startswith("/Users/")
        or value.startswith("/home/")
        or str(ROOT) in value
    ):
        fail(f"absolute JSON path remains at {where}: {value}", failures)


def check_bundle_json_paths(bundle: Path, failures: list[str]) -> None:
    for path in sorted(bundle.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        inspect_json_for_absolute_paths(payload, str(path), failures)


def check_operating_point_embedding(primary: Path, failures: list[str]) -> None:
    """Check the frozen profile-to-feeder constants in the result manifest."""

    path = primary / "result_manifest.json"
    if not path.is_file():
        fail(f"missing result manifest for operating-point embedding: {path}", failures)
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        embedding = payload["operating_point_embedding"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
        fail(f"result manifest lacks operating_point_embedding: {exc}", failures)
        return
    expected = {
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
    }
    for key, value in expected.items():
        if embedding.get(key) != value:
            fail(
                f"operating_point_embedding.{key}={embedding.get(key)!r}; expected {value!r}",
                failures,
            )


def check_bundle_inventory(bundle: Path, failures: list[str]) -> None:
    if not bundle.is_dir():
        fail(f"missing bundle directory: {bundle}", failures)
        return
    for required in (
        "main.tex",
        "RecoveryFlex_AE_2026_manuscript.pdf",
        "Highlights.txt",
        "cover_letter.txt",
        "requirements.txt",
        "pytest.ini",
        "data/processed",
        "data/raw/README.md",
        "data/raw/feeder_manifest.json",
        "data/raw/THIRD_PARTY_LICENSES.txt",
        "data/raw/IEEE13Nodeckt.dss",
        "data/raw/IEEELineCodes.dss",
        "data/raw/IEEE13Node_BusXY.csv",
        "data/raw/ausgrid/README.md",
        "data/raw/ieee123_snapshot/master.dss",
        "data/raw/ieee123_snapshot/Buscoords.dss",
        "data/raw/ieee123_snapshot/IEEE123Loads.dss",
        "data/raw/ieee123_snapshot/IEEE123Regulators.dss",
        "data/raw/ieee123_snapshot/IEEELinecodes.dss",
        "data/processed/ausgrid_profile_bank_v2_index.csv",
        "data/processed/opsd_profile_bank_v2_index.csv",
        "PACKAGE_MANIFEST.json",
        "RecoveryFlex_AE_2026_journal_source.zip",
        "RecoveryFlex_AE_2026_source.zip",
        "SHA256SUMS.txt",
    ):
        if not (bundle / required).exists():
            fail(f"bundle is missing {required}", failures)
    main = bundle / "main.tex"
    if main.exists():
        text = main.read_text(encoding="utf-8", errors="replace")
        if "\\graphicspath{{figures/}}" not in text:
            fail("bundle main.tex does not set graphicspath to figures/", failures)
        for name in re.findall(r"\\includegraphics(?:\[[^]]*\])?\{([^}]+)\}", text):
            if not any((bundle / "figures" / f"{name}{suffix}").is_file() for suffix in (".pdf", ".png", ".jpg", ".jpeg")):
                fail(f"figure referenced by main.tex is missing: {name}", failures)
    for name in ("AUTHOR_AND_SUBMISSION_CHECKLIST.md", "NOT_READY.txt"):
        if not (bundle / name).is_file():
            fail(f"bundle is missing author/status file: {name}", failures)
    for path in bundle.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(bundle)
        if any(part.startswith("chunk_") for part in relative.parts):
            fail(f"parallel chunk artifact present in bundle: {relative}", failures)
        if relative.parts[:2] == ("data", "raw") and relative.as_posix() not in RAW_REPRO_FILES:
            fail(f"raw input file present in bundle: {relative}", failures)
    check_bundle_json_paths(bundle, failures)

    package_manifest = bundle / "PACKAGE_MANIFEST.json"
    if package_manifest.exists():
        try:
            payload = json.loads(package_manifest.read_text(encoding="utf-8"))
            package_files = payload.get("files", {})
            if not isinstance(package_files, dict):
                raise ValueError("files is not an object")
            for relative, digest in package_files.items():
                path = bundle / relative
                if not path.is_file():
                    fail(f"package manifest points to missing file: {relative}", failures)
                elif sha256(path) != digest:
                    fail(f"package manifest hash mismatch: {relative}", failures)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            fail(f"invalid PACKAGE_MANIFEST.json: {exc}", failures)

    checksums = bundle / "SHA256SUMS.txt"
    if checksums.exists():
        seen: set[str] = set()
        for line in checksums.read_text(encoding="utf-8", errors="replace").splitlines():
            match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            if not match:
                fail(f"invalid checksum line: {line}", failures)
                continue
            digest, relative = match.groups()
            seen.add(relative)
            path = bundle / relative
            if not path.is_file():
                fail(f"checksum points to missing file: {relative}", failures)
            elif sha256(path) != digest:
                fail(f"checksum mismatch: {relative}", failures)
        actual = {
            path.relative_to(bundle).as_posix()
            for path in bundle.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS.txt"
        }
        if actual != seen:
            fail("SHA256SUMS.txt does not cover exactly the package files except itself", failures)

    archive = bundle / "RecoveryFlex_AE_2026_source.zip"
    if archive.exists():
        try:
            with zipfile.ZipFile(archive) as handle:
                names = set(handle.namelist())
            for required in ("src/", "tests/", "scripts/", "docs/", "data/processed/", "results/"):
                if not any(name.startswith(required) for name in names):
                    fail(f"source ZIP missing required tree: {required}", failures)
            if "requirements.txt" not in names:
                fail("source ZIP has no requirements.txt", failures)
            if "pytest.ini" not in names:
                fail("source ZIP has no pytest.ini/pythonpath configuration", failures)
            if not any(name.startswith("data/processed/") and name.endswith(".npz") for name in names):
                fail("source ZIP has no processed NPZ input", failures)
            if not any(name.startswith("data/raw/") for name in names):
                fail("source ZIP has no raw-source acquisition notes", failures)
            for name in names:
                if name.startswith("data/raw/") and name not in RAW_REPRO_FILES:
                    fail(f"unallow-listed raw input appears in source ZIP: {name}", failures)
        except (OSError, zipfile.BadZipFile) as exc:
            fail(f"invalid source ZIP: {exc}", failures)

    journal_archive = bundle / "RecoveryFlex_AE_2026_journal_source.zip"
    if journal_archive.exists():
        try:
            with zipfile.ZipFile(journal_archive) as handle:
                names = set(handle.namelist())
            if "main.tex" not in names:
                fail("journal source ZIP has no main.tex", failures)
            figure_names = {name for name in names if name.startswith("figures/")}
            if not figure_names:
                fail("journal source ZIP has no figures/ files", failures)
            allowed = {"main.tex"} | figure_names
            unexpected = sorted(names - allowed)
            if unexpected:
                fail(
                    "journal source ZIP contains non-journal/internal files: "
                    + ", ".join(unexpected[:8]),
                    failures,
                )
            forbidden_members = {
                "cover_letter.txt",
                "README.md",
                "MANIFEST.md",
                "PACKAGE_MANIFEST.json",
                "NOT_READY.txt",
                "RESEARCH_STATUS.txt",
            }
            if forbidden_members & names or any(name.startswith("docs/reviews/") for name in names):
                fail("journal source ZIP contains an internal status/review artifact", failures)
        except (OSError, zipfile.BadZipFile) as exc:
            fail(f"invalid journal source ZIP: {exc}", failures)


def check_v4(bundle: Path, require_metadata: bool, failures: list[str], config_key: str = "v4") -> None:
    config = CONFIG[config_key]
    manuscript = resolve(config["manuscript"])
    pdf = resolve(config["pdf"])
    primary = resolve(config["primary"])
    figures = resolve(config["figures"])
    text = manuscript.read_text(encoding="utf-8", errors="replace") if manuscript.exists() else ""
    for path in (manuscript, pdf, primary, figures):
        if not path.exists():
            fail(f"missing v4 input: {path}", failures)
    check_pdf_pages(pdf, int(config["expected_pages"]), failures)
    figure_numbers = (6, 7, 8, 9, 10, 11) if config_key == "v5" else (6, 7)
    check_results_float_order(pdf, failures, figure_numbers)
    packaged_pdf = bundle / "RecoveryFlex_AE_2026_manuscript.pdf"
    check_results_float_order(packaged_pdf, failures, figure_numbers)
    approved_title = "Network-audited chronological delivery limits for repeated distribution-battery flexibility"
    if config_key == "v5" and approved_title not in text:
        fail("v5 manuscript does not use the approved network-audited repeated-flexibility title", failures)
    if config_key == "v5":
        packaged_main = bundle / "main.tex"
        if packaged_main.is_file() and approved_title not in packaged_main.read_text(encoding="utf-8", errors="replace"):
            fail("bundle main.tex title is out of sync with the current manuscript", failures)
        packaged_cff = bundle / "CITATION.cff"
        if packaged_cff.is_file() and approved_title not in packaged_cff.read_text(encoding="utf-8", errors="replace"):
            fail("bundle CITATION.cff title is out of sync with the current manuscript", failures)
        try:
            packaged_title_text = subprocess.check_output(
                ["pdftotext", "-f", "1", "-l", "1", str(bundle / "RecoveryFlex_AE_2026_manuscript.pdf"), "-"],
                text=True,
            )
            normalized_title_text = " ".join(packaged_title_text.split())
            if approved_title not in normalized_title_text:
                fail("bundle PDF title is out of sync with the current manuscript", failures)
        except (OSError, subprocess.CalledProcessError):
            fail("could not inspect bundle PDF title", failures)
    for forbidden in (
        "risk-calibrated",
        "procurement study",
        "95% reliable",
        "guaranteed external review",
        "_mwh",
        "deliverable_coverage",
    ):
        if forbidden.casefold() in text.casefold():
            fail(f"stale or overclaiming v4 phrase: {forbidden}", failures)
    if require_metadata and ("to be completed" in text or "[Department" in text):
        fail("author affiliation/e-mail placeholders remain", failures)

    stats = read_csv(primary / "statistics" / "method_summary.csv", failures)
    required = [
        ("611.3", "baseline_feasible", "network_lp", "service_kw", "date"),
        ("634.1", "baseline_feasible", "network_lp", "service_kw", "date"),
        ("634.1", "baseline_feasible", "myopic_recovery", "service_kw", "date"),
        ("611.3", "baseline_feasible", "energy_only", "replay_feasible", "date"),
        ("634.1", "baseline_feasible", "energy_only", "replay_feasible", "date"),
    ]
    for site, population, method, outcome, cluster in required:
        candidate = row(stats, site=site, population=population, method=method, outcome=outcome, cluster_level=cluster)
        assert_number_from_row(text, candidate, f"strict-v4 {site}/{method}/{outcome}", failures)
    baseline_rows = [r for r in stats if r.get("population") == "baseline_feasible" and r.get("method") == "network_lp" and r.get("outcome") == "service_kw" and r.get("cluster_level") == "date"]
    all_rows = [r for r in stats if r.get("population") == "all" and r.get("method") == "network_lp" and r.get("outcome") == "service_kw" and r.get("cluster_level") == "date"]
    if baseline_rows and all_rows:
        dates = {int(r["n_clusters"]) for r in baseline_rows}
        expected_baseline_units = sum(int(r["n_pairs"]) for r in baseline_rows)
        expected_all_units = sum(int(r["n_pairs"]) for r in all_rows)
        if len(dates) == 1 and not number_in_text(text, float(next(iter(dates)))):
            fail(f"manuscript is missing CSV-derived date count: {next(iter(dates))}", failures)
        if len(baseline_rows) == 2 and not number_in_text(text, float(expected_baseline_units // 2)):
            fail(f"manuscript is missing CSV-derived baseline-unit count: {expected_baseline_units // 2}", failures)
        audit = read_csv(primary / "baseline_zero_audit.csv", failures)
        passed = sum(str(r.get("baseline_zero_feasible", "")).lower() in {"1", "true"} for r in audit)
        if len(audit) != expected_all_units or passed != expected_baseline_units:
            fail(f"baseline audit rows/pass={len(audit)}/{passed}, CSV-derived expected={expected_all_units}/{expected_baseline_units}", failures)

    capacity = read_csv(resolve(Path("results/capacity_sensitivity_strict_v4")) / "statistics.csv", failures)
    capacity_rows: list[dict[str, str]] = []
    for energy in ("250.0", "500.0", "1000.0", "2000.0"):
        candidate = row(capacity, population="baseline_feasible", site="634.1", capacity_kwh=energy, method="network_lp", outcome="service_kw", cluster_level="date")
        assert_number_from_row(text, candidate, f"capacity 634.1/{energy} kWh", failures)
        if candidate is not None:
            capacity_rows.append(candidate)
    if capacity_rows:
        values = [float(r["estimate"]) for r in capacity_rows]
        if any(right + 1e-6 < left for left, right in zip(values, values[1:])):
            fail(f"capacity frontier is not nondecreasing in CSV: {values}", failures)

    safe = read_csv(resolve(Path("results/safe_offer_metrics_strict_v4")) / "safe_offer_metrics.csv", failures)
    if safe:
        columns = set(safe[0])
        missing = {"mean_shortfall_kwh", "frontier_replay_coverage"} - columns
        if missing:
            fail(f"safe-offer CSV is missing v4 columns: {sorted(missing)}", failures)
        if {"mean_shortfall_mwh", "deliverable_coverage"} & columns:
            fail("safe-offer CSV still uses superseded v3 column names", failures)
        for site in ("611.3", "634.1"):
            candidate = row(safe, site=site, method="network_lp", target_empirical_coverage="0.95")
            if candidate is None:
                fail(f"missing v4 95% network safe-offer row at {site}", failures)
            else:
                for field in ("offer_kw", "mean_shortfall_kwh", "frontier_replay_coverage"):
                    try:
                        value = float(candidate[field])
                    except (KeyError, ValueError):
                        fail(f"invalid safe-offer value at {site}/{field}", failures)
                        continue
                    if field != "frontier_replay_coverage" and not number_in_text(text, value):
                        fail(f"manuscript lacks CSV-derived safe-offer value {value:.6f} at {site}/{field}", failures)

    if config_key == "v5":
        check_operating_point_embedding(primary, failures)
        package_primary = bundle / "results" / primary.name
        check_operating_point_embedding(package_primary, failures)
        margin = read_csv(resolve(Path("results/headroom_margin_sensitivity_strict_v4")) / "date_cluster_summary.csv", failures)
        for selectors in (
            dict(site="634.1", margin="0.2", method="network_lp"),
            dict(site="611.3", margin="0.2", method="network_lp"),
        ):
            candidate = row(margin, **selectors)
            assert_number_from_row(text, candidate, f"headroom margin {selectors}", failures)
        common_path = resolve(Path("results/common_offer_replay_strict_v5/summary.json"))
        try:
            common_payload = json.loads(common_path.read_text(encoding="utf-8"))
            common_results = common_payload["results"]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            fail(f"invalid common-threshold replay summary: {exc}", failures)
            common_results = []
        for site, threshold in (("611.3", 89.296875), ("634.1", 83.203125)):
            candidates = [item for item in common_results if str(item.get("site")) == site]
            if len(candidates) != 1:
                fail(f"missing common-threshold replay summary at {site}", failures)
                continue
            item = candidates[0]
            if not close(float(item.get("threshold_kw", float("nan"))), threshold, 1e-6):
                fail(f"common-threshold value mismatch at {site}: {item.get('threshold_kw')}", failures)
            if not close(float(item.get("replay_feasible_rate", float("nan"))), 0.95018281535649, 1e-9):
                fail(f"common-threshold replay rate mismatch at {site}: {item.get('replay_feasible_rate')}", failures)
            if not number_in_text(text, threshold):
                fail(f"manuscript lacks common-threshold value at {site}: {threshold}", failures)

        binding_path = resolve(Path("results/binding_ablation_strict_v5/two_mwh_binding_summary.csv"))
        binding = read_csv(binding_path, failures)
        for site in ("611.3", "634.1"):
            candidate = row(binding, source="ausgrid", site=site, population="baseline_feasible")
            if candidate is None:
                fail(f"missing 2-MWh binding audit row at {site}", failures)
                continue
            try:
                equal = int(candidate["n_equal_tolerance"])
                units = int(candidate["n_units"])
            except (KeyError, ValueError):
                fail(f"invalid 2-MWh binding audit row at {site}", failures)
                continue
            if equal != units or units != 2188:
                fail(f"2-MWh binding audit mismatch at {site}: {equal}/{units}", failures)
            if not number_in_text(text, float(equal)):
                fail(f"manuscript lacks binding-audit count at {site}: {equal}", failures)
        package_binding = bundle / "results" / "binding_ablation_strict_v5" / "two_mwh_binding_summary.csv"
        if not package_binding.is_file():
            fail(f"bundle is missing binding audit summary: {package_binding}", failures)
        location_binding_path = resolve(Path("results/location_sensitivity_external_2012_2013_strict_v4/statistics/binding_audit/two_mwh_binding_summary.csv"))
        location_binding = read_csv(location_binding_path, failures)
        baseline_location = [r for r in location_binding if r.get("population") == "baseline_feasible"]
        if len(baseline_location) != 7:
            fail(f"location binding audit has {len(baseline_location)} baseline-feasible site rows; expected 7", failures)
        for candidate in baseline_location:
            try:
                equal = int(candidate["n_equal_tolerance"])
                units = int(candidate["n_units"])
            except (KeyError, ValueError):
                fail(f"invalid location binding row: {candidate}", failures)
                continue
            if units != 2188 or equal != units:
                fail(f"location 2-MWh binding mismatch at {candidate.get('site')}: {equal}/{units}", failures)
        package_location = bundle / "results" / "location_sensitivity_external_2012_2013_strict_v4" / "statistics" / "binding_audit" / "two_mwh_binding_summary.csv"
        if not package_location.is_file():
            fail(f"bundle is missing location binding audit summary: {package_location}", failures)

    check_bundle_inventory(bundle, failures)
    if "to be completed" not in text and "[Department" not in text:
        for metadata_name in ("NOT_READY.txt", "README.md", "RESEARCH_STATUS.txt"):
            metadata_path = bundle / metadata_name
            if metadata_path.is_file() and "affiliation/e-mail completion" in metadata_path.read_text(encoding="utf-8", errors="replace").casefold():
                fail(f"{metadata_name} retains an obsolete affiliation/e-mail completion gate", failures)
    for result_path in [config["primary"], *config["extras"]]:
        result_name = Path(result_path).name
        if not (bundle / "results" / result_name).is_dir():
            fail(f"bundle is missing declared result directory: results/{result_name}", failures)


def check_v3(bundle: Path, require_metadata: bool, failures: list[str]) -> None:
    config = CONFIG["v3"]
    manuscript = resolve(config["manuscript"])
    pdf = resolve(config["pdf"])
    primary = resolve(config["primary"])
    figures = resolve(config["figures"])
    for path in (manuscript, pdf, primary, figures):
        if not path.exists():
            fail(f"missing v3 input: {path}", failures)
    text = manuscript.read_text(encoding="utf-8", errors="replace") if manuscript.exists() else ""
    for forbidden in ("risk-calibrated", "procurement study", "95% reliable", "guaranteed external review"):
        if forbidden.casefold() in text.casefold():
            fail(f"stale or overclaiming v3 phrase: {forbidden}", failures)
    if require_metadata and ("to be completed" in text or "[Department" in text):
        fail("author affiliation/e-mail placeholders remain", failures)
    stats = read_csv(primary / "statistics" / "method_summary.csv", failures)
    for selectors in (
        dict(site="611.3", population="baseline_feasible", method="network_lp", outcome="service_kw", cluster_level="date"),
        dict(site="634.1", population="baseline_feasible", method="network_lp", outcome="service_kw", cluster_level="date"),
        dict(site="634.1", population="baseline_feasible", method="myopic_recovery", outcome="service_kw", cluster_level="date"),
    ):
        assert_number_from_row(text, row(stats, **selectors), f"strict-v3 {selectors}", failures)
    check_pdf_pages(pdf, 11, failures)
    if bundle.exists():
        main = bundle / "main.tex"
        if main.exists() and "\\graphicspath{{figures/}}" not in main.read_text(encoding="utf-8", errors="replace"):
            fail("v3 bundle main.tex does not set graphicspath to figures/", failures)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=sorted(CONFIG), default="v4")
    parser.add_argument("--bundle-dir", type=Path, default=None)
    parser.add_argument("--require-metadata", action="store_true")
    args = parser.parse_args()
    config = CONFIG[args.version]
    bundle = resolve(args.bundle_dir if args.bundle_dir is not None else config["bundle"])
    failures: list[str] = []
    if args.version in {"v4", "v5"}:
        check_v4(bundle, args.require_metadata, failures, args.version)
    else:
        check_v3(bundle, args.require_metadata, failures)
    if failures:
        print(f"FINAL_PACKAGE_CHECK_{args.version.upper()}: FAIL")
        for item in failures:
            print(f"- {item}")
        return 1
    print(f"FINAL_PACKAGE_CHECK_{args.version.upper()}: PASS")
    print(f"{args.version} manuscript, CSV-derived statistics, result records, and package checks are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
