#!/usr/bin/env python3
"""Copy referenced local uploads to a private S3-compatible bucket.

The default is a dry run. Use --apply only after configuring and testing the
private destination bucket. Local source files are never deleted by this script.
"""
from __future__ import annotations

import argparse
import json

from app.core.database import connect_db
from app.services.object_storage import migrate_local_uploads_to_s3, storage_backend


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Copy files to S3; otherwise only report the plan.")
    args = parser.parse_args()

    if storage_backend() != "s3":
        parser.error("Set UPLOAD_STORAGE_BACKEND=s3 and configure S3_BUCKET before running.")

    with connect_db() as conn:
        report_rows = conn.execute(
            "SELECT image_path FROM reports WHERE image_path IS NOT NULL"
        ).fetchall()
        evidence_rows = conn.execute(
            "SELECT image_path FROM claim_evidence_images"
        ).fetchall()
    keys = [row["image_path"] for row in [*report_rows, *evidence_rows] if row["image_path"]]
    result = migrate_local_uploads_to_s3(keys, dry_run=not args.apply)
    print(json.dumps({
        "mode": "apply" if args.apply else "dry-run",
        "referenced_keys": len(set(keys)),
        **result,
        "local_sources_deleted": 0,
    }, indent=2))
    if result["missing"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
