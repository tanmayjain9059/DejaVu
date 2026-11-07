#!/usr/bin/env python3
"""Export every object from the configured private S3-compatible bucket.

The destination must be an empty directory. The resulting flat directory can
be passed to scripts/backup_uploads.sh for an encrypted age archive.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from app.core.object_storage import _object_settings, _safe_key, _s3_client, object_storage_enabled


def export_bucket(destination: Path, client, bucket: str) -> tuple[int, int]:
    """Download all objects safely; return object count and total bytes."""
    if destination.is_symlink():
        raise RuntimeError("Refusing to export into a symlink.")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise RuntimeError("Export destination must be empty.")
    paginator = client.get_paginator("list_objects_v2")
    count = total_bytes = 0
    for page in paginator.paginate(Bucket=bucket):
        for item in page.get("Contents", []):
            key = _safe_key(item.get("Key"))
            target = (destination / key).resolve()
            if target.parent != destination.resolve():
                raise RuntimeError(f"Unsafe object key: {key!r}")
            response = client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read()
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
            count += 1
            total_bytes += len(content)
    return count, total_bytes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if not object_storage_enabled():
        raise RuntimeError("Configure all OBJECT_STORAGE_* variables before exporting.")
    bucket = _object_settings()[0]
    count, total_bytes = export_bucket(args.destination, _s3_client(), bucket)
    print(f"Exported {count} objects ({total_bytes} bytes) from private bucket {bucket!r}.")
    print("Encrypt this export before moving it off the backup host.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Object-storage export failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
