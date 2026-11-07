#!/usr/bin/env python3
"""Restore flat upload files into the configured private S3-compatible bucket.

Dry-run is the default. Pass --execute only after verifying the restored
source directory and the destination bucket.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app.core.object_storage import _safe_key, object_storage_enabled, store_upload


def import_directory(source: Path, execute: bool = False) -> tuple[int, int]:
    if source.is_symlink() or not source.is_dir():
        raise RuntimeError("Source uploads path must be an existing real directory.")
    count = total_bytes = 0
    for entry in sorted(source.iterdir()):
        if entry.is_symlink() or not entry.is_file():
            raise RuntimeError(f"Unexpected non-file entry in source uploads: {entry.name!r}")
        key = _safe_key(entry.name)
        content = entry.read_bytes()
        if execute:
            store_upload(key, content)
        count += 1
        total_bytes += len(content)
    return count, total_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--execute", action="store_true", help="Upload files; without this flag only validate and report.")
    args = parser.parse_args()
    if not object_storage_enabled():
        raise RuntimeError("Configure all OBJECT_STORAGE_* variables before importing.")
    count, total_bytes = import_directory(args.source, execute=args.execute)
    action = "Uploaded" if args.execute else "Validated"
    print(f"{action} {count} files ({total_bytes} bytes).")
    if not args.execute:
        print("Dry run only. No objects uploaded. Re-run with --execute to restore.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Object-storage import failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
