#!/usr/bin/env python3
"""Copy referenced local LostLink uploads into the configured private object bucket.

The database stores stable object keys (filenames), so this script does not
rewrite database rows. Dry-run is the default; pass --execute to upload bytes.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import DB_PATH, UPLOAD_DIR
from app.core.object_storage import object_storage_enabled, store_upload


def referenced_uploads(database: Path) -> list[str]:
    if not database.is_file():
        raise FileNotFoundError(f"Database not found: {database}")
    with sqlite3.connect(database) as conn:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {"reports", "claim_evidence_images"}
        missing = required - tables
        if missing:
            raise RuntimeError("Database is missing expected tables: " + ", ".join(sorted(missing)))
        values = set()
        for table in ("reports", "claim_evidence_images"):
            values.update(
                row[0] for row in conn.execute(
                    f"SELECT image_path FROM {table} WHERE image_path IS NOT NULL AND image_path <> ''"
                )
            )
    keys = []
    for value in sorted(values):
        key = str(value)
        if Path(key).name != key or key in {".", ".."} or "/" in key or "\\" in key:
            raise RuntimeError(f"Unsafe upload key in database: {key!r}")
        keys.append(key)
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DB_PATH)
    parser.add_argument("--source-uploads", type=Path, default=UPLOAD_DIR)
    parser.add_argument("--execute", action="store_true", help="Upload files; without this flag only validate and report.")
    args = parser.parse_args()

    if not object_storage_enabled():
        raise RuntimeError("Configure all OBJECT_STORAGE_* variables before running this migration.")
    keys = referenced_uploads(args.database)
    missing = [key for key in keys if not (args.source_uploads / key).is_file()]
    if missing:
        raise RuntimeError("Referenced source uploads are missing: " + ", ".join(missing))
    print(f"Found {len(keys)} unique referenced uploads.")
    if not args.execute:
        print("Dry run only. No objects uploaded. Re-run with --execute to copy them.")
        return 0

    for index, key in enumerate(keys, start=1):
        source = (args.source_uploads / key).resolve()
        if source.parent != args.source_uploads.resolve():
            raise RuntimeError(f"Upload path escapes source directory: {key!r}")
        store_upload(key, source.read_bytes())
        print(f"[{index}/{len(keys)}] Uploaded {key}")
    print("Upload copy complete. Verify image access in the hosted app before retiring the source directory.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Upload migration failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
