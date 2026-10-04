#!/usr/bin/env python3
"""Verify the manifest and path hygiene of an extracted public snapshot.

The public release is deliberately a plain directory so that a reviewer can
run this check after extracting the ZIP without access to the development
checkout.  ``PUBLIC_SNAPSHOT_MANIFEST.json`` lists each payload file together
with its SHA-256 digest and byte count.  The verifier never follows symlinks,
rejects absolute/path-traversal entries, and reports a non-zero exit status on
the first missing, extra, or mismatched file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_relative(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"manifest path is not relative to the snapshot: {value!r}")
    if not value or value.endswith("/"):
        raise ValueError(f"manifest path is not a regular file path: {value!r}")
    return candidate


def verify(snapshot: Path) -> tuple[int, int]:
    manifest_path = snapshot / "PUBLIC_SNAPSHOT_MANIFEST.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise FileNotFoundError(f"missing manifest: {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = payload.get("files")
    if not isinstance(entries, list):
        raise ValueError("manifest field 'files' must be a list")

    expected: dict[Path, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError(f"invalid manifest entry: {entry!r}")
        relative = safe_relative(str(entry["path"]))
        if relative in expected:
            raise ValueError(f"duplicate manifest path: {relative}")
        digest = entry.get("sha256")
        size = entry.get("bytes")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError(f"invalid SHA-256 for {relative}")
        if not isinstance(size, int) or size < 0:
            raise ValueError(f"invalid byte count for {relative}")
        expected[relative] = entry

    actual: set[Path] = set()
    for path in snapshot.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"symlink is not allowed in public snapshot: {path}")
        if path.is_file() and path.name != "PUBLIC_SNAPSHOT_MANIFEST.json":
            actual.add(path.relative_to(snapshot))
    missing = sorted(set(expected) - actual)
    extra = sorted(actual - set(expected))
    if missing:
        raise ValueError("manifest-listed files missing: " + ", ".join(map(str, missing[:8])))
    if extra:
        raise ValueError("unlisted files present: " + ", ".join(map(str, extra[:8])))

    checked = 0
    for relative, entry in sorted(expected.items(), key=lambda item: str(item[0])):
        path = snapshot / relative
        if path.stat().st_size != int(entry["bytes"]):
            raise ValueError(f"byte count mismatch: {relative}")
        observed = sha256(path)
        if observed != str(entry["sha256"]):
            raise ValueError(f"SHA-256 mismatch: {relative}")
        checked += 1
    return checked, len(extra)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path("."), help="extracted snapshot directory")
    args = parser.parse_args()
    snapshot = args.snapshot.expanduser().resolve()
    checked, _ = verify(snapshot)
    print(f"PUBLIC_SNAPSHOT_CHECK: PASS ({checked} files; {snapshot})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
