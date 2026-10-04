#!/usr/bin/env python3
"""Build a reproducible, pre-submission manuscript bundle.

The builder intentionally treats the manuscript and result directories as
inputs.  It does not run experiments, compile LaTeX, publish a release, or
declare the package ready for submission.  It copies the requested v4
manuscript and figures, the selected result directories, the source needed to
reproduce them, and frozen processed metadata.  JSON provenance paths are
rewritten to package-relative paths after copying so the package does not
depend on the creator's absolute checkout path.

Example::

    python scripts/build_submission_bundle.py \
      --manuscript paper/main_v4.tex \
      --pdf paper/main_v4.pdf \
      --figures-dir paper/figures_v4 \
      --results-dir results/network_recovery_external_2012_2013_strict_v4 \
      --out-dir submission_bundle_v4 \
      --extra-results results/capacity_sensitivity_strict_v4 \
      --extra-results results/causal_capacity_sensitivity_strict_v4 \
      --extra-results results/safe_offer_metrics_strict_v4

The command is deliberately explicit about the primary result directory and
any additional result directories.  Large development/raw archives are not
discovered or copied from ``data/raw``.  A small allow-list of public static
feeder fixtures and licence notices is copied so an extracted bundle can run
its AC tests without network access; old result directories are rejected when
passed as inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_METADATA_DIR = ROOT / "submission_bundle"
OLD_RESULT_MARKERS = (
    "_v0",
    "_v1",
    "_v2",
    "_v3",
    "_dev",
    "_smoke",
    "corrected_",
    "editorial_",
    "factorial_",
    "candidate_",
    "parallel_",
)
EXCLUDED_DIR_NAMES = {"__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}

# These small public files are required by the bundled OpenDSS tests.  Keep
# this explicit rather than traversing ``data/raw``: household archives and
# QSTS profile trees are intentionally acquisition-only and can be very large.
REPRO_RAW_FILES = (
    "README.md",
    "feeder_manifest.json",
    "THIRD_PARTY_LICENSES.txt",
    "IEEE13Nodeckt.dss",
    "IEEELineCodes.dss",
    "IEEE13Node_BusXY.csv",
    "ausgrid/README.md",
    "ieee123_snapshot/manifest.json",
    "ieee123_snapshot/master.dss",
    "ieee123_snapshot/Buscoords.dss",
    "ieee123_snapshot/IEEE123Loads.dss",
    "ieee123_snapshot/IEEE123Regulators.dss",
    "ieee123_snapshot/IEEELinecodes.dss",
    "ieee123_qsts/manifest.json",
)


@dataclass(frozen=True)
class PathMap:
    """Map an absolute source subtree to a package-relative subtree."""

    source: Path
    destination: Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_rel(path: Path) -> str:
    return path.as_posix()


def is_regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.suffix not in EXCLUDED_SUFFIXES


def ensure_inside(path: Path, parent: Path, label: str) -> Path:
    parent_resolved = parent.resolve()
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = parent_resolved / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(parent_resolved)
    except ValueError as exc:
        raise ValueError(f"{label} must be inside the repository: {path}") from exc
    return resolved


def reject_old_result(path: Path, label: str) -> None:
    lowered = path.name.casefold()
    if lowered in {"three_call_grid_v1", "three_call_replay_v1"}:
        return
    if any(marker in lowered for marker in OLD_RESULT_MARKERS):
        raise ValueError(
            f"{label} looks like a superseded/development result directory: {path}. "
            "Pass only the declared current result or sensitivity outputs."
        )


def copy_file(source: Path, destination: Path) -> None:
    if not is_regular_file(source):
        raise FileNotFoundError(f"source file is missing or not a regular file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(
    source: Path,
    destination: Path,
    *,
    skip_chunks: bool = False,
    skip_uncompressed_failure_records: bool = False,
) -> list[Path]:
    """Copy regular files below *source* and return destination files."""

    copied: list[Path] = []
    if not source.is_dir():
        raise FileNotFoundError(f"source directory is missing: {source}")
    for path in sorted(source.rglob("*")):
        if not is_regular_file(path):
            continue
        relative = path.relative_to(source)
        if any(part in EXCLUDED_DIR_NAMES for part in relative.parts):
            continue
        if skip_chunks and any(part.startswith("chunk_") for part in relative.parts):
            continue
        if skip_uncompressed_failure_records and path.name == "failure_records.csv":
            compressed = path.with_name("failure_records.csv.gz")
            if compressed.exists():
                continue
        target = destination / relative
        copy_file(path, target)
        copied.append(target)
    return copied


def collect_processed_files(root: Path) -> list[tuple[Path, Path]]:
    """Collect frozen processed manifests and arrays, excluding raw data.

    Every JSON/NPZ directly under ``data/processed`` is treated as processed
    metadata or a derived array.  Raw archives and old experiment outputs live
    elsewhere and are never traversed by this function.
    """

    source_dir = root / "data" / "processed"
    if not source_dir.is_dir():
        return []
    selected: list[tuple[Path, Path]] = []
    for source in sorted(source_dir.iterdir()):
        if not is_regular_file(source):
            continue
        if source.suffix.lower() not in {".json", ".npz", ".csv"}:
            continue
        # The two index tables are tiny derived metadata used by the
        # chronological split tests.  Other processed CSV outputs, if added
        # later, should be requested explicitly instead of silently bundled.
        if source.suffix.lower() == ".csv" and not source.name.endswith("_index.csv"):
            continue
        selected.append((source, Path("data") / "processed" / source.name))
    required_indices = {
        "ausgrid_profile_bank_v2_index.csv",
        "opsd_profile_bank_v2_index.csv",
    }
    present_indices = {source.name for source, _ in selected if source.suffix.lower() == ".csv"}
    missing_indices = sorted(required_indices - present_indices)
    if missing_indices:
        raise FileNotFoundError(
            "required processed index table is missing: " + ", ".join(missing_indices)
        )
    return selected


def collect_source_files(root: Path) -> list[tuple[Path, Path]]:
    """Collect current source, tests, scripts, docs, and root metadata."""

    selected: list[tuple[Path, Path]] = []
    for dirname in ("src", "tests", "scripts", "docs"):
        source_dir = root / dirname
        if not source_dir.is_dir():
            continue
        for source in sorted(source_dir.rglob("*")):
            if not is_regular_file(source):
                continue
            relative = source.relative_to(root)
            if any(part in EXCLUDED_DIR_NAMES for part in relative.parts):
                continue
            selected.append((source, relative))
    for name in (
        "requirements.txt",
        "novelty_firewall.md",
        "pytest.ini",
    ):
        source = root / name
        if is_regular_file(source):
            selected.append((source, Path(name)))
    return selected


def collect_provenance_files(root: Path) -> list[tuple[Path, Path]]:
    """Collect allow-listed feeder fixtures and acquisition notes.

    Static feeder files are small and are included for a clean extracted-bundle
    test run.  No other raw directory is traversed, so third-party household
    archives and QSTS profiles remain excluded.
    """

    selected: list[tuple[Path, Path]] = []
    for relative in REPRO_RAW_FILES:
        source = root / "data" / "raw" / relative
        if not is_regular_file(source):
            raise FileNotFoundError(
                f"required reproducibility fixture is missing: {source}"
            )
        selected.append((source, source.relative_to(root)))
    return selected


def resolve_metadata_file(metadata_dir: Path, root: Path, name: str) -> Path | None:
    for candidate in (metadata_dir / name, root / name):
        if is_regular_file(candidate):
            return candidate
    return None


def rewrite_graphicspath(text: str) -> str:
    """Force the copied manuscript to resolve figures from ``figures/``."""

    lines = text.splitlines(keepends=True)
    replaced = False
    result: list[str] = []
    for line in lines:
        if line.lstrip().startswith("\\graphicspath"):
            newline = "\n" if line.endswith("\n") else ""
            result.append("\\graphicspath{{figures/}}" + newline)
            replaced = True
        else:
            result.append(line)
    if replaced:
        return "".join(result)
    joined = "".join(result)
    marker = "\\begin{document}"
    if marker not in joined:
        raise ValueError("manuscript does not contain \\begin{document}")
    return joined.replace(marker, "\\graphicspath{{figures/}}\n" + marker, 1)


def map_absolute_path(value: str, mappings: Iterable[PathMap], root: Path) -> str:
    """Convert an absolute repository path to a package-relative path."""

    if not value.startswith("/"):
        return value
    candidate = Path(value).expanduser()
    for mapping in sorted(mappings, key=lambda item: len(item.source.parts), reverse=True):
        try:
            relative = candidate.relative_to(mapping.source)
        except ValueError:
            continue
        return clean_rel(mapping.destination / relative)
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return value
    return clean_rel(relative)


def rewrite_json(value: Any, mappings: Iterable[PathMap], root: Path) -> Any:
    if isinstance(value, dict):
        rewritten: dict[Any, Any] = {}
        for key, item in value.items():
            # Result manifests store file paths as dictionary keys.  Rewriting
            # only values leaves absolute keys behind and breaks package-local
            # provenance, so path-looking keys receive the same relocation.
            new_key = (
                map_absolute_path(key, mappings, root)
                if isinstance(key, str)
                else key
            )
            rewritten[new_key] = rewrite_json(item, mappings, root)
        return rewritten
    if isinstance(value, list):
        return [rewrite_json(item, mappings, root) for item in value]
    if isinstance(value, str):
        return map_absolute_path(value, mappings, root)
    return value


def rewrite_package_json(out_dir: Path, mappings: list[PathMap], root: Path) -> None:
    for path in sorted(out_dir.rglob("*.json")):
        if not is_regular_file(path):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        path.write_text(
            json.dumps(rewrite_json(payload, mappings, root), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def prune_relocated_result_manifests(out_dir: Path) -> None:
    """Drop manifest entries for intentionally excluded chunk artifacts.

    The source result manifest may have been produced before a package build
    and can therefore mention parallel chunk files that are deliberately not
    copied.  After path relocation, retaining those keys would make the
    package manifest claim files that do not exist.  Hashes for files that
    remain are recalculated against the relocated package contents.
    """

    for path in sorted(out_dir.rglob("result_manifest.json")):
        if not is_regular_file(path):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        files = payload.get("files")
        if not isinstance(files, dict):
            continue
        retained = {
            key: value
            for key, value in files.items()
            if (
                isinstance(key, str)
                and not Path(key).is_absolute()
                and ".." not in Path(key).parts
                and (out_dir / key).is_file()
            )
        }
        # Recalculate every retained hash after path relocation.  The source
        # bytes normally stay unchanged, but this makes the package manifest
        # self-consistent even when an input manifest was stale or partial.
        retained = {
            key: sha256(out_dir / key)
            for key in sorted(retained)
        }
        payload["files"] = retained
        payload["status"] = "package_relocated_result_manifest"
        payload["path_policy"] = "All paths are relative to this package; excluded chunk artifacts are omitted."
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def rewrite_metadata_version(text: str, version: str, *, author_metadata_ready: bool = False) -> str:
    """Update active package status wording without inventing readiness."""

    text = re.sub(r"strict[- ]v[23]\b", f"strict-{version}", text, flags=re.IGNORECASE)
    if author_metadata_ready:
        text = re.sub(
            r"followed by affiliation/e-mail completion",
            "followed by the final author/editorial read",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"affiliation/e-mail completion",
            "the final author/editorial read",
            text,
            flags=re.IGNORECASE,
        )
    return text


def package_files(out_dir: Path, *, exclude: set[str] | None = None) -> list[Path]:
    excluded = exclude or set()
    return sorted(
        path
        for path in out_dir.rglob("*")
        if is_regular_file(path) and clean_rel(path.relative_to(out_dir)) not in excluded
    )


def write_package_manifest(out_dir: Path, *, manuscript: Path, primary_results: Path, extras: list[Path]) -> Path:
    manifest_path = out_dir / "PACKAGE_MANIFEST.json"
    excluded = {
        clean_rel(manifest_path.relative_to(out_dir)),
        "SHA256SUMS.txt",
        "RecoveryFlex_AE_2026_source.zip",
        "RecoveryFlex_AE_2026_journal_source.zip",
    }
    files = {
        clean_rel(path.relative_to(out_dir)): sha256(path)
        for path in package_files(out_dir, exclude=excluded)
    }
    payload = {
        "schema_version": 1,
        "status": "pre_submission_development_bundle",
        "manuscript_input": "main.tex",
        "primary_results": clean_rel(Path("results") / primary_results.name),
        "extra_results": [clean_rel(Path("results") / path.name) for path in extras],
        "figures": "figures/",
        "path_policy": "JSON paths are package-relative; allow-listed static feeder fixtures are included with third-party notices, while large raw archives and superseded result directories are excluded.",
        "files": files,
    }
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def write_manifest_markdown(out_dir: Path, primary: Path, extras: list[Path]) -> Path:
    path = out_dir / "MANIFEST.md"
    lines = [
        "# Applied Energy pre-submission development bundle",
        "",
        "This package is a reproducible internal development bundle. It is not an Editorial Manager upload and makes no claim of acceptance or guaranteed external review.",
        "",
        "## Contents",
        "",
        f"- `main.tex` and `RecoveryFlex_AE_2026_manuscript.pdf`: copied manuscript source and PDF.",
        "- `Highlights.txt` and `Highlights.docx`: manuscript-matched highlights in plain-text and editable Word formats; `cover_letter.txt` is the manuscript-matched draft.",
        "- `figures/`: copied article figures and graphical abstract with the manuscript's `graphicspath` set to `figures/`.",
        f"- `results/{primary.name}/`: declared primary result directory, copied without chunk intermediates.",
    ]
    for extra in extras:
        lines.append(f"- `results/{extra.name}/`: explicitly requested additional sensitivity result.")
    lines.extend(
        [
            "- `src/`, `tests/`, `scripts/`, `docs/`, `requirements.txt`, and `data/processed/`: reproducibility source and frozen processed metadata.",
            "- `PACKAGE_MANIFEST.json`: package-relative file manifest and SHA-256 hashes; its own hash and both ZIP hashes are covered by `SHA256SUMS.txt`.",
            "- `RecoveryFlex_AE_2026_journal_source.zip`: clean Editorial Manager source archive containing only `main.tex` and the article figures; it excludes the cover letter and internal review/status files.",
            "- `RecoveryFlex_AE_2026_source.zip`: deterministic internal reproducibility snapshot excluding both ZIP archives and `SHA256SUMS.txt`; do not upload this archive to the journal.",
            "- `SHA256SUMS.txt`: SHA-256 hashes for every package file except this checksum file.",
            "",
            "Small static IEEE-13 and IEEE-123 feeder fixtures needed by the bundled AC tests are included under `data/raw/` with their source hashes and third-party notices.",
            "Large raw household archives, the IEEE-123 QSTS profile tree, superseded result directories, and parallel chunk directories are excluded; acquisition notes and hashes remain in `data/raw/`.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_deterministic_zip(out_dir: Path) -> Path:
    archive = out_dir / "RecoveryFlex_AE_2026_source.zip"
    excluded = {
        clean_rel(archive.relative_to(out_dir)),
        "RecoveryFlex_AE_2026_journal_source.zip",
        "SHA256SUMS.txt",
    }
    files = package_files(out_dir, exclude=excluded)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in files:
            relative = clean_rel(path.relative_to(out_dir))
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            handle.writestr(info, path.read_bytes())
    return archive


def write_journal_source_zip(out_dir: Path) -> Path:
    """Write the minimal source archive suitable for a journal upload.

    The development bundle intentionally contains internal review material and
    reproducibility metadata.  Editorial Manager should receive only the
    transformed manuscript source and its figure files, with the cover letter
    uploaded separately at the journal interface.
    """

    archive = out_dir / "RecoveryFlex_AE_2026_journal_source.zip"
    files = [out_dir / "main.tex", *sorted((out_dir / "figures").rglob("*"))]
    files = [path for path in files if is_regular_file(path)]
    required = {"main.tex"}
    names = {clean_rel(path.relative_to(out_dir)) for path in files}
    if not required.issubset(names) or not any(name.startswith("figures/") for name in names):
        raise FileNotFoundError("journal source archive requires main.tex and figures/")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in files:
            relative = clean_rel(path.relative_to(out_dir))
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            handle.writestr(info, path.read_bytes())
    return archive


def write_sha256sums(out_dir: Path) -> Path:
    checksum_path = out_dir / "SHA256SUMS.txt"
    files = package_files(out_dir, exclude={"SHA256SUMS.txt"})
    lines = [f"{sha256(path)}  {clean_rel(path.relative_to(out_dir))}" for path in files]
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checksum_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", choices=("v4", "v5"), default=None)
    parser.add_argument("--manuscript", type=Path, default=Path("paper/main_v4.tex"))
    parser.add_argument("--pdf", type=Path, default=Path("paper/main_v4.pdf"))
    parser.add_argument("--figures-dir", type=Path, default=Path("paper/figures_v4"))
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("results/network_recovery_external_2012_2013_strict_v4"),
    )
    parser.add_argument("--out-dir", type=Path, default=Path("submission_bundle_v4"))
    parser.add_argument("--extra-results", type=Path, action="append", default=[])
    parser.add_argument("--highlights", type=Path, default=Path("paper/Highlights_v4.txt"))
    parser.add_argument("--cover-letter", type=Path, default=Path("paper/cover_letter_v4.txt"))
    parser.add_argument("--metadata-dir", type=Path, default=DEFAULT_METADATA_DIR)
    parser.add_argument("--force", action="store_true", help="replace an existing output directory")
    return parser.parse_args()


def build(args: argparse.Namespace) -> Path:
    manuscript = ensure_inside(args.manuscript, ROOT, "manuscript")
    version = args.version or ("v5" if manuscript.stem.endswith("_v5") else "v4")
    pdf = ensure_inside(args.pdf, ROOT, "PDF")
    figures_dir = ensure_inside(args.figures_dir, ROOT, "figures directory")
    primary_results = ensure_inside(args.results_dir, ROOT, "primary results directory")
    extras = [ensure_inside(path, ROOT, "extra results directory") for path in args.extra_results]
    highlights = ensure_inside(args.highlights, ROOT, "highlights")
    highlights_docx = highlights.with_suffix(".docx")
    cover_letter = ensure_inside(args.cover_letter, ROOT, "cover letter")
    metadata_dir = ensure_inside(args.metadata_dir, ROOT, "metadata directory")
    out_candidate = args.out_dir.expanduser()
    if not out_candidate.is_absolute():
        out_candidate = ROOT / out_candidate
    out_dir = out_candidate.resolve()
    if primary_results in extras or len({path.name for path in [primary_results, *extras]}) != len([primary_results, *extras]):
        raise ValueError("primary and extra result directory names must be unique")
    reject_old_result(primary_results, "primary results directory")
    for extra in extras:
        reject_old_result(extra, "extra results directory")
    for required in (manuscript, pdf, highlights, cover_letter):
        if not is_regular_file(required):
            raise FileNotFoundError(required)
    for directory in (figures_dir, primary_results, *extras):
        if not directory.is_dir():
            raise FileNotFoundError(directory)
    if out_dir.exists() and any(out_dir.iterdir()) and not args.force:
        raise FileExistsError(f"output directory is not empty; use --force to replace it: {out_dir}")
    input_paths = [manuscript, pdf, highlights, cover_letter, figures_dir, primary_results, *extras, metadata_dir]
    if is_regular_file(highlights_docx):
        input_paths.append(highlights_docx)
    if out_dir == ROOT or any(out_dir == path or out_dir in path.parents or path in out_dir.parents for path in input_paths):
        raise ValueError(
            "output directory must be separate from the repository root and every input path"
        )

    parent = out_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out_dir.name}.tmp-", dir=parent))
    try:
        # Manuscript and journal-facing artifacts.
        manuscript_text = rewrite_graphicspath(manuscript.read_text(encoding="utf-8"))
        author_metadata_ready = "to be completed" not in manuscript_text and "[Department" not in manuscript_text
        (temporary / "main.tex").write_text(manuscript_text, encoding="utf-8")
        copy_file(pdf, temporary / "RecoveryFlex_AE_2026_manuscript.pdf")
        copy_file(highlights, temporary / "Highlights.txt")
        if is_regular_file(highlights_docx):
            copy_file(highlights_docx, temporary / "Highlights.docx")
        copy_file(cover_letter, temporary / "cover_letter.txt")
        copy_tree(figures_dir, temporary / "figures")

        # Author status and repository metadata.  Existing metadata is copied
        # verbatim so the builder does not invent affiliations or readiness.
        for name in (
            "AUTHOR_AND_SUBMISSION_CHECKLIST.md",
            "NOT_READY.txt",
            "RESEARCH_STATUS.txt",
            "README.md",
            "CITATION.cff",
            "LICENSE",
        ):
            # Author/status files may be supplied from a package-specific
            # metadata directory.  Repository identity files stay sourced
            # from the checkout so an older bundle cannot overwrite a newer
            # README or citation record by accident.
            source_dir = metadata_dir if name in {
                "AUTHOR_AND_SUBMISSION_CHECKLIST.md",
                "NOT_READY.txt",
            } else ROOT
            source = resolve_metadata_file(source_dir, ROOT, name)
            if source is not None:
                destination = temporary / name
                if name in {
                    "AUTHOR_AND_SUBMISSION_CHECKLIST.md",
                    "NOT_READY.txt",
                    "RESEARCH_STATUS.txt",
                    "README.md",
                }:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_text(
                        rewrite_metadata_version(
                            source.read_text(encoding="utf-8"),
                            version,
                            author_metadata_ready=author_metadata_ready,
                        ),
                        encoding="utf-8",
                    )
                else:
                    copy_file(source, destination)

        # Reproducibility source, allow-listed feeder fixtures, and frozen
        # processed files.  No other data/raw path is traversed, and no result
        # directory is copied here.
        for source, relative in [
            *collect_source_files(ROOT),
            *collect_processed_files(ROOT),
            *collect_provenance_files(ROOT),
        ]:
            # Do not let an existing output directory be recursively included
            # when the caller chooses an in-repository output path.
            if out_dir in source.parents:
                continue
            copy_file(source, temporary / relative)

        mappings = [PathMap(primary_results, Path("results") / primary_results.name)]
        mappings.extend(PathMap(extra, Path("results") / extra.name) for extra in extras)
        mappings.append(PathMap(figures_dir, Path("figures")))
        # Frozen result manifests from earlier runs commonly point at a
        # repository-level ``figures/network_recovery_*`` directory, whereas
        # the bundle deliberately flattens the selected figure directory to
        # ``figures/``.  Add each existing repository figure subtree as an
        # exact mapping so both its directory field and its file keys remain
        # valid after relocation.
        repository_figures = ROOT / "figures"
        if repository_figures.is_dir():
            for source_figure_dir in sorted(repository_figures.iterdir()):
                if source_figure_dir.is_dir():
                    mappings.append(PathMap(source_figure_dir.resolve(), Path("figures")))
        mappings.append(PathMap(ROOT / "data" / "processed", Path("data") / "processed"))
        copy_tree(
            primary_results,
            temporary / "results" / primary_results.name,
            skip_chunks=True,
            skip_uncompressed_failure_records=True,
        )
        for extra in extras:
            copy_tree(
                extra,
                temporary / "results" / extra.name,
                skip_chunks=True,
                skip_uncompressed_failure_records=True,
            )
        rewrite_package_json(temporary, mappings, ROOT)
        prune_relocated_result_manifests(temporary)

        # Make the package-level inventory after all copied JSON has been
        # rewritten.  This manifest is explicit even when an input result
        # manifest was generated with absolute paths.
        write_manifest_markdown(temporary, primary_results, extras)
        write_package_manifest(
            temporary,
            manuscript=manuscript,
            primary_results=primary_results,
            extras=extras,
        )
        write_journal_source_zip(temporary)
        write_deterministic_zip(temporary)
        write_sha256sums(temporary)

        if out_dir.exists():
            shutil.rmtree(out_dir)
        temporary.rename(out_dir)
        return out_dir
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    args = parse_args()
    output = build(args)
    print(f"Built pre-submission development bundle: {output}")
    print("No experiment, compilation, upload, or release action was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
