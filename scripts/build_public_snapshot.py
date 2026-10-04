#!/usr/bin/env python3
"""Build the curated, runnable public snapshot from an internal bundle.

The internal submission bundle contains author metadata, cover-letter drafts,
review records, and package archives that are useful for audit but should not
be published as the reproducibility snapshot.  This script keeps the public
surface explicit and copies the complete source, tests, result directories,
figures, and the small licensed data fixtures.  It also includes the full
three-call drivers, the public-snapshot verifier, and the Eq. (8) note; older
protocol/data-validity files are copied only when they carry their ARCHIVAL
marker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path


TOP_LEVEL = (
    "CITATION.cff",
    "Highlights.docx",
    "Highlights.txt",
    "LICENSE",
    "README.md",
    "RecoveryFlex_AE_2026_manuscript.pdf",
    "main.tex",
    "pytest.ini",
    "requirements.txt",
)
PUBLIC_DOCS = (
    "ai_use_record_v5.md",
    "block_stratified_bootstrap_v1.md",
    "data_validity_audit.json",
    "decision_chain_v6.md",
    "eq8_reproducibility_note_v1.md",
    "experiment_protocol_corrected_v1.md",
    "experiment_protocol_v1.md",
    "experiment_protocol_v2.md",
    "experiment_protocol_v4.md",
    "final_experiment_plan.md",
    "literature_matrix.md",
    "reference_doi_audit_v5.md",
    "reproducibility_v5.md",
    "runtime_environment_v5.txt",
    "runtime_execution_v6.txt",
)
PUBLIC_DIRS = ("data", "figures", "results", "scripts", "src", "tests")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.suffix not in {".pyc", ".pyo"}


def copy_one(source: Path, destination: Path) -> None:
    if not regular(source):
        raise FileNotFoundError(f"missing regular source file: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise FileNotFoundError(f"missing source directory: {source}")
    for path in sorted(source.rglob("*")):
        if not regular(path):
            continue
        relative = path.relative_to(source)
        if "__pycache__" in relative.parts or ".pytest_cache" in relative.parts:
            continue
        copy_one(path, destination / relative)


def assert_archival_markers(source: Path) -> None:
    for name in ("experiment_protocol_v1.md", "experiment_protocol_v2.md", "experiment_protocol_v4.md", "final_experiment_plan.md", "experiment_protocol_corrected_v1.md"):
        text = (source / "docs" / name).read_text(encoding="utf-8")
        if not text.startswith("**ARCHIVAL"):
            raise ValueError(f"stale public protocol lacks ARCHIVAL marker: docs/{name}")
    payload = json.loads((source / "docs" / "data_validity_audit.json").read_text(encoding="utf-8"))
    if payload.get("document_status") != "archival_historical_audit":
        raise ValueError("docs/data_validity_audit.json lacks archival_historical_audit status")


def write_manifest(root: Path) -> Path:
    files = []
    for path in sorted(root.rglob("*")):
        if not regular(path) or path.name == "PUBLIC_SNAPSHOT_MANIFEST.json":
            continue
        relative = path.relative_to(root).as_posix()
        files.append({"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size})
    manifest = {
        "snapshot": "RecoveryFlex-AE public reproducibility snapshot",
        "title": "RecoveryFlex-AE",
        "created_from": "submission_bundle_v5",
        "files": files,
    }
    output = root / "PUBLIC_SNAPSHOT_MANIFEST.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def write_zip(root: Path) -> Path:
    archive = root.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as handle:
        for path in sorted(root.rglob("*")):
            if not regular(path):
                continue
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            handle.writestr(info, path.read_bytes())
    return archive


def build(bundle: Path, output: Path, force: bool) -> tuple[Path, Path]:
    bundle = bundle.expanduser().resolve()
    output = output.expanduser().resolve()
    if not bundle.is_dir():
        raise FileNotFoundError(bundle)
    if output == bundle or output in bundle.parents:
        raise ValueError("public output must be separate from the internal bundle")
    assert_archival_markers(bundle)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        for name in TOP_LEVEL:
            copy_one(bundle / name, temporary / name)
        for name in PUBLIC_DOCS:
            copy_one(bundle / "docs" / name, temporary / "docs" / name)
        for name in PUBLIC_DIRS:
            copy_tree(bundle / name, temporary / name)
        write_manifest(temporary)
        if output.exists():
            if not force:
                raise FileExistsError(f"output exists; pass --force: {output}")
            shutil.rmtree(output)
        temporary.rename(output)
        manifest = output / "PUBLIC_SNAPSHOT_MANIFEST.json"
        archive = write_zip(output)
        return manifest, archive
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("submission_bundle_v5"))
    parser.add_argument("--out-dir", type=Path, default=Path("release_candidate_v5_public"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    manifest, archive = build(args.bundle, args.out_dir, args.force)
    print(f"Built public snapshot: {manifest.parent}")
    print(f"Manifest: {manifest}")
    print(f"Archive: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
