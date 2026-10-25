#!/usr/bin/env python3
"""Explicit, conservative SQLite -> PostgreSQL data migration.

The destination schema is bootstrapped first and must be empty. The source database
is opened read-only. No source data is deleted. Run once in a maintenance window.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

TABLE_ORDER = (
    "users",
    "login_attempts",
    "reports",
    "claims",
    "audit_events",
    "notifications",
    "reward_ledger",
    "certificates",
    "handovers",
    "claim_verifications",
    "claim_evidence_images",
)
BATCH_SIZE = 500


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True, type=Path, help="Path to the existing SQLite database")
    parser.add_argument("--source-uploads", required=True, type=Path, help="Directory containing existing uploaded images")
    parser.add_argument("--execute", action="store_true", help="Perform the migration; without this flag only validate and report")
    return parser.parse_args()


def sqlite_tables(connection):
    return {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def safe_upload_path(root: Path, filename: str) -> Path:
    root = root.resolve()
    candidate = (root / filename).resolve()
    if candidate.parent != root:
        raise RuntimeError(f"Unsafe upload path recorded in database: {filename!r}")
    return candidate


def main():
    args = parse_args()
    load_dotenv()
    if not os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL must point to an empty PostgreSQL destination.")
    if not args.source_db.is_file():
        raise SystemExit(f"SQLite source database does not exist: {args.source_db}")
    if not args.source_uploads.is_dir():
        raise SystemExit(f"Source upload directory does not exist: {args.source_uploads}")

    # Prevent demo seeding when preparing a migration target.
    os.environ["DEMO_MODE"] = "false"
    from app.core import database
    from app.core import config

    database.DATABASE_URL = config.DATABASE_URL
    database.UPLOAD_DIR = config.UPLOAD_DIR
    database.DEMO_MODE = False
    database.initialise_db()

    source = sqlite3.connect(str(args.source_db.resolve()))
    source.row_factory = sqlite3.Row
    source.execute("PRAGMA query_only = ON")
    integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise SystemExit(f"Source SQLite integrity check failed: {integrity}")
    foreign_key_errors = source.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise SystemExit(f"Source SQLite has foreign-key violations: {len(foreign_key_errors)}")

    source_tables = sqlite_tables(source)
    unsupported = source_tables - set(TABLE_ORDER) - {"schema_migrations"}
    if unsupported:
        raise SystemExit("Unknown source tables need explicit migration handling: " + ", ".join(sorted(unsupported)))

    counts = {}
    referenced_uploads = set()
    for table in TABLE_ORDER:
        if table not in source_tables:
            counts[table] = 0
            continue
        counts[table] = source.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if table == "reports":
            referenced_uploads.update(
                row[0] for row in source.execute(
                    "SELECT image_path FROM reports WHERE image_path IS NOT NULL AND TRIM(image_path)<>''"
                )
            )
        elif table == "claim_evidence_images":
            referenced_uploads.update(
                row[0] for row in source.execute(
                    "SELECT image_path FROM claim_evidence_images WHERE image_path IS NOT NULL AND TRIM(image_path)<>''"
                )
            )

    upload_pairs = []
    for filename in sorted(referenced_uploads):
        source_path = safe_upload_path(args.source_uploads, filename)
        target_path = safe_upload_path(database.UPLOAD_DIR, filename)
        if not source_path.is_file():
            raise SystemExit(f"Referenced upload is missing; migration stopped: {source_path}")
        if target_path.exists():
            raise SystemExit(f"Destination upload already exists; migration stopped: {target_path}")
        upload_pairs.append((source_path, target_path))

    with database.connect_db() as target:
        for table in TABLE_ORDER:
            if table not in source_tables:
                continue
            if target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]:
                raise SystemExit(
                    f"Destination table {table!r} is not empty. Use a fresh PostgreSQL database; "
                    "this script never merges into populated data."
                )

    print("SQLite source integrity and foreign-key checks: OK")
    print("Destination schema: bootstrapped; all destination application tables are empty")
    print("Rows to copy:")
    for table, count in counts.items():
        print(f"  {table}: {count}")
    print(f"Referenced image files to copy: {len(upload_pairs)}")
    if not args.execute:
        print("DRY RUN ONLY — no records or files were copied. Re-run with --execute to migrate.")
        source.close()
        database.close_database_pool()
        return 0

    copied_files = []
    try:
        # Copy private uploads first. If a DB write fails, remove only files copied by this run.
        for source_path, target_path in upload_pairs:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            copied_files.append(target_path)

        with database.connect_db() as target:
            for table in TABLE_ORDER:
                if table not in source_tables:
                    continue
                source_columns = [row[1] for row in source.execute(f'PRAGMA table_info("{table}")')]
                target_columns = database.table_columns(target, table)
                columns = [name for name in source_columns if name in target_columns]
                if not columns:
                    continue
                placeholders = ", ".join("?" for _ in columns)
                quoted_columns = ", ".join('"' + name.replace('"', '""') + '"' for name in columns)
                insert_sql = f'INSERT INTO "{table}" ({quoted_columns}) VALUES ({placeholders})'
                cursor = source.execute(f'SELECT {quoted_columns} FROM "{table}"')
                while True:
                    rows = cursor.fetchmany(BATCH_SIZE)
                    if not rows:
                        break
                    target.executemany(insert_sql, [tuple(row[name] for name in columns) for row in rows])

            # Preserve future auto-increment IDs after importing explicit primary keys.
            if isinstance(target, database.PostgresCompatConnection):
                for table in ("users", "audit_events"):
                    sequence = target.execute(
                        "SELECT pg_get_serial_sequence(?, 'id') AS sequence", (table,)
                    ).fetchone()["sequence"]
                    if sequence:
                        target.execute(
                            f"SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {table}), 1), "
                            f"EXISTS(SELECT 1 FROM {table}))",
                            (sequence,),
                        )

            for table, expected in counts.items():
                actual = target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if actual != expected:
                    raise RuntimeError(
                        f"Row-count verification failed for {table}: source={expected}, destination={actual}"
                    )

        print("Migration committed. Row counts match for every migrated table.")
        print("Source SQLite database and source uploads were not modified.")
        return 0
    except Exception:
        for path in copied_files:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        source.close()
        database.close_database_pool()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        raise
