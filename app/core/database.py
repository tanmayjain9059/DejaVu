"""SQLite connections, migrations, audit events and optional demo seeding."""
from __future__ import annotations
import hashlib, json, os, re, sqlite3, uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from PIL import UnidentifiedImageError
from app.core.config import *
from app.core.images import perceptual_hash_from_bytes
from app.core.security import hash_password


class PostgresCompatRow(dict):
    """PostgreSQL result row supporting both name and numeric-index access."""

    def __init__(self, column_names, values):
        self._ordered_values = tuple(values)
        super().__init__(zip(column_names, self._ordered_values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._ordered_values[key]
        return super().__getitem__(key)


def postgres_row_factory(cursor):
    """Psycopg row factory that mirrors sqlite3.Row indexing behaviour."""
    description = cursor.description or ()
    column_names = [
        column.name if hasattr(column, "name") else column[0]
        for column in description
    ]
    return lambda values: PostgresCompatRow(column_names, values)


def _translate_placeholders(statement: str) -> str:
    """Translate SQLite positional placeholders without touching quoted text/comments."""
    output: list[str] = []
    index = 0
    quote: str | None = None
    line_comment = False
    block_comment = False

    while index < len(statement):
        char = statement[index]
        next_pair = statement[index:index + 2]

        if line_comment:
            output.append(char)
            if char == "\n":
                line_comment = False
            index += 1
            continue

        if block_comment:
            if next_pair == "*/":
                output.append(next_pair)
                block_comment = False
                index += 2
            else:
                output.append(char)
                index += 1
            continue

        if quote:
            output.append(char)
            if char == quote:
                if index + 1 < len(statement) and statement[index + 1] == quote:
                    output.append(statement[index + 1])
                    index += 2
                    continue
                quote = None
            index += 1
            continue

        if next_pair == "--":
            output.append(next_pair)
            line_comment = True
            index += 2
        elif next_pair == "/*":
            output.append(next_pair)
            block_comment = True
            index += 2
        elif char in ("'", '"'):
            quote = char
            output.append(char)
            index += 1
        elif char == "?":
            output.append("%s")
            index += 1
        else:
            output.append(char)
            index += 1

    return "".join(output)


class PostgresCompatConnection:
    """Limited DB-API compatibility for the SQLite-style SQL used by this project."""

    def __init__(self, connection):
        self._connection = connection

    @staticmethod
    def translate(sql: str) -> tuple[str, bool]:
        statement = sql.strip()
        if statement.upper() == "BEGIN IMMEDIATE":
            return "SELECT pg_advisory_xact_lock(730021)", True

        ignored_insert = re.match(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", statement, re.I)
        replace_insert = re.match(r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\s+claim_verifications\b", statement, re.I)
        if ignored_insert:
            statement = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", statement, flags=re.I).rstrip().rstrip(";")
            statement += " ON CONFLICT DO NOTHING"
        elif replace_insert:
            statement = re.sub(r"^\s*INSERT\s+OR\s+REPLACE\s+INTO\b", "INSERT INTO", statement, flags=re.I).rstrip().rstrip(";")
            statement += (
                " ON CONFLICT (claim_id) DO UPDATE SET "
                "verifier_user_id=EXCLUDED.verifier_user_id, "
                "checks_json=EXCLUDED.checks_json, verified_at=EXCLUDED.verified_at"
            )
        return _translate_placeholders(statement), False

    def execute(self, sql: str, parameters=()):
        statement, _ = self.translate(sql)
        return self._connection.execute(statement, parameters or ())

    def executemany(self, sql: str, parameters):
        statement, _ = self.translate(sql)
        results = []
        for parameter_set in parameters:
            results.append(self._connection.execute(statement, parameter_set))
        return results

    def executescript(self, script: str) -> None:
        script = re.sub(r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT", "SERIAL PRIMARY KEY", script, flags=re.I)
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        return self._connection.commit()

    def rollback(self):
        return self._connection.rollback()

    def close(self):
        return self._connection.close()


def _postgres_url() -> str:
    if not DATABASE_URL:
        return ""
    if DATABASE_URL.startswith("postgres://"):
        return "postgresql://" + DATABASE_URL[len("postgres://"):]
    if DATABASE_URL.startswith("postgresql://"):
        return DATABASE_URL
    raise RuntimeError("DATABASE_URL must use postgresql:// or postgres://.")


_POSTGRES_POOL = None


def _get_postgres_pool():
    """Create a bounded connection pool on demand for managed PostgreSQL."""
    global _POSTGRES_POOL
    if _POSTGRES_POOL is not None:
        return _POSTGRES_POOL
    try:
        from psycopg_pool import ConnectionPool
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_URL is configured for PostgreSQL, but psycopg with its pool extra "
            "is not installed. Install the project requirements."
        ) from exc
    try:
        max_size = int(os.getenv("DATABASE_POOL_MAX_SIZE", "5"))
    except ValueError as exc:
        raise RuntimeError("DATABASE_POOL_MAX_SIZE must be an integer between 1 and 20.") from exc
    if not 1 <= max_size <= 20:
        raise RuntimeError("DATABASE_POOL_MAX_SIZE must be between 1 and 20.")
    _POSTGRES_POOL = ConnectionPool(
        conninfo=_postgres_url(),
        min_size=1,
        max_size=max_size,
        kwargs={"row_factory": postgres_row_factory, "connect_timeout": 10},
        timeout=10,
        open=True,
    )
    return _POSTGRES_POOL


def close_database_pool() -> None:
    """Release pooled PostgreSQL connections during application shutdown."""
    global _POSTGRES_POOL
    if _POSTGRES_POOL is not None:
        _POSTGRES_POOL.close()
        _POSTGRES_POOL = None


@contextmanager
def connect_db():
    if DATABASE_URL:
        pool = _get_postgres_pool()
        # psycopg_pool commits successful transactions, rolls back on exceptions,
        # and returns the connection to the pool on context exit.
        with pool.connection() as raw_connection:
            yield PostgresCompatConnection(raw_connection)
        return

    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def table_columns(conn, table_name: str) -> set[str]:
    """Return column names without depending on SQLite-only PRAGMA syntax."""
    if isinstance(conn, PostgresCompatConnection):
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table_name,),
        ).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(conn: sqlite3.Connection, actor_id: int, action: str,
          entity_type: str, entity_id: str, details: dict[str, Any] | None = None) -> None:
    conn.execute(
        """INSERT INTO audit_events(actor_id, action, entity_type, entity_id, details_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (actor_id, action, entity_type, entity_id, json.dumps(details or {}), now_iso()),
    )


def initialise_db() -> None:
    with connect_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('student', 'office')),
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS login_attempts (
                subject TEXT PRIMARY KEY,
                failure_count INTEGER NOT NULL DEFAULT 0,
                window_started_at TEXT NOT NULL,
                locked_until TEXT
            );
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                public_ref TEXT NOT NULL UNIQUE,
                report_type TEXT NOT NULL CHECK(report_type IN ('lost', 'found')),
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                brand TEXT,
                primary_color TEXT,
                visible_features TEXT,
                category TEXT NOT NULL,
                occurred_at TEXT,
                location_block TEXT,
                location_floor TEXT,
                location_room TEXT,
                location_area TEXT,
                image_path TEXT,
                image_sha256 TEXT,
                image_phash TEXT,
                status TEXT NOT NULL,
                closure_reason TEXT,
                closure_note TEXT,
                created_by INTEGER NOT NULL REFERENCES users(id),
                tag_id TEXT UNIQUE,
                storage_location TEXT,
                private_detail TEXT,
                value_band TEXT NOT NULL DEFAULT 'unknown',
                sensitivity_level INTEGER NOT NULL DEFAULT 1,
                verification_level INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
                id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL REFERENCES reports(id),
                lost_report_id TEXT REFERENCES reports(id),
                claimant_id INTEGER NOT NULL REFERENCES users(id),
                evidence TEXT NOT NULL,
                evidence_types TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                appeal_note TEXT,
                appeal_count INTEGER NOT NULL DEFAULT 0,
                reviewer_id INTEGER REFERENCES users(id),
                reviewer_note TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_id INTEGER NOT NULL REFERENCES users(id),
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                event_key TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                read_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, event_key)
            );
            CREATE TABLE IF NOT EXISTS reward_ledger (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                event_key TEXT NOT NULL,
                points INTEGER NOT NULL CHECK(points > 0),
                reason TEXT NOT NULL,
                report_id TEXT REFERENCES reports(id),
                created_at TEXT NOT NULL,
                UNIQUE(user_id, event_key)
            );
            CREATE TABLE IF NOT EXISTS certificates (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                tier TEXT NOT NULL,
                threshold_points INTEGER NOT NULL,
                points_at_issue INTEGER NOT NULL,
                serial TEXT NOT NULL UNIQUE,
                issued_at TEXT NOT NULL,
                UNIQUE(user_id, tier)
            );
            CREATE TABLE IF NOT EXISTS handovers (
                id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL UNIQUE REFERENCES claims(id),
                report_id TEXT NOT NULL UNIQUE REFERENCES reports(id),
                tag_id TEXT NOT NULL,
                claimant_id INTEGER NOT NULL REFERENCES users(id),
                office_user_id INTEGER NOT NULL REFERENCES users(id),
                handover_note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claim_verifications (
                claim_id TEXT PRIMARY KEY REFERENCES claims(id),
                verifier_user_id INTEGER NOT NULL REFERENCES users(id),
                checks_json TEXT NOT NULL,
                verified_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claim_evidence_images (
                id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL UNIQUE REFERENCES claims(id) ON DELETE CASCADE,
                uploader_id INTEGER NOT NULL REFERENCES users(id),
                image_path TEXT NOT NULL,
                image_sha256 TEXT NOT NULL,
                image_phash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_user_created ON notifications(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_reward_ledger_user_created ON reward_ledger(user_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_reports_status_type ON reports(status, report_type);
            CREATE INDEX IF NOT EXISTS idx_reports_category ON reports(category);
            CREATE INDEX IF NOT EXISTS idx_claims_report ON claims(report_id, status);
            CREATE INDEX IF NOT EXISTS idx_claims_claimant ON claims(claimant_id, created_at);
            """
        )
        # Keep existing local databases compatible as storage tracking is introduced.
        report_columns = table_columns(conn, "reports")
        if "storage_location" not in report_columns:
            conn.execute("ALTER TABLE reports ADD COLUMN storage_location TEXT")
        conn.execute(
            "UPDATE reports SET storage_location=? WHERE tag_id IS NOT NULL AND (storage_location IS NULL OR TRIM(storage_location)='')",
            ("Location needs confirmation",),
        )
        # Backward-compatible migrations for richer item details and report closure.
        report_columns = table_columns(conn, "reports")
        for column, declaration in (
            ("brand", "TEXT"),
            ("primary_color", "TEXT"),
            ("visible_features", "TEXT"),
            ("closure_reason", "TEXT"),
            ("closure_note", "TEXT"),
            ("image_sha256", "TEXT"),
            ("image_phash", "TEXT"),
        ):
            if column not in report_columns:
                conn.execute(f"ALTER TABLE reports ADD COLUMN {column} {declaration}")
        for image_row in conn.execute(
            "SELECT id, image_path, image_sha256, image_phash FROM reports WHERE image_path IS NOT NULL"
        ).fetchall():
            image_path = (UPLOAD_DIR / image_row["image_path"]).resolve()
            if image_path.parent != UPLOAD_DIR.resolve() or not image_path.is_file():
                continue
            if image_row["image_sha256"] and image_row["image_phash"]:
                continue
            try:
                image_bytes = image_path.read_bytes()
                image_digest = image_row["image_sha256"] or hashlib.sha256(image_bytes).hexdigest()
                image_phash = image_row["image_phash"] or perceptual_hash_from_bytes(image_bytes)
                conn.execute(
                    "UPDATE reports SET image_sha256=?, image_phash=? WHERE id=?",
                    (image_digest, image_phash, image_row["id"]),
                )
            except (OSError, UnidentifiedImageError, ValueError):
                continue
        claim_columns = table_columns(conn, "claims")
        for column, declaration in (
            ("appeal_note", "TEXT"),
            ("appeal_count", "INTEGER NOT NULL DEFAULT 0"),
            ("lost_report_id", "TEXT REFERENCES reports(id)"),
            ("evidence_types", "TEXT NOT NULL DEFAULT '[]'"),
        ):
            if column not in claim_columns:
                conn.execute(f"ALTER TABLE claims ADD COLUMN {column} {declaration}")
        # Record the current legacy bootstrap as the initial schema baseline.
        # Existing additive compatibility updates above remain safe to re-run; future
        # schema changes must receive a new ordered migration version.
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
            (1, "legacy_schema_baseline", now_iso()),
        )
        if not DEMO_MODE:
            return

        conn.execute(
            """INSERT OR IGNORE INTO users(email, display_name, role, password_hash, created_at)
               VALUES (?, ?, 'student', ?, ?)""",
            ("student@lostlink.local", "Demo Student", hash_password("student123"), now_iso()),
        )
        conn.execute(
            """INSERT OR IGNORE INTO users(email, display_name, role, password_hash, created_at)
               VALUES (?, ?, 'office', ?, ?)""",
            ("office@lostlink.local", "Campus Office", hash_password("office123"), now_iso()),
        )
        for email, display_name, password in (
            ("student2@lostlink.local", "Aarav Mehta", "student2123"),
            ("student3@lostlink.local", "Riya Sharma", "student3123"),
            ("student4@lostlink.local", "Kabir Rao", "student4123"),
        ):
            conn.execute(
                """INSERT OR IGNORE INTO users(email, display_name, role, password_hash, created_at)
                   VALUES (?, ?, 'student', ?, ?)""",
                (email, display_name, hash_password(password), now_iso()),
            )
        student_id = conn.execute("SELECT id FROM users WHERE email=?", ("student@lostlink.local",)).fetchone()["id"]
        office_id = conn.execute("SELECT id FROM users WHERE email=?", ("office@lostlink.local",)).fetchone()["id"]
        if conn.execute("SELECT COUNT(*) AS n FROM reports").fetchone()["n"] > 0:
            return

        today = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        examples = [
            {
                "public_ref": "LL-P7K4Q2", "report_type": "found", "title": "Navy backpack",
                "description": "Dark blue backpack with two front pockets and a silver zipper pull.",
                "category": "bags_wallets", "days": 1, "block": "Block A", "floor": "1",
                "room": "A-101", "area": "Library entrance", "status": "available",
                "creator": office_id, "tag": "LL-CVR-" + str(today.year) + "-000001",
                "private": "Small silver zipper pull on the front pocket and a tiny stitched mark inside the left strap.",
                "value": "medium", "sensitivity": 1, "level": 2,
            },
            {
                "public_ref": "LL-M3T8H1", "report_type": "found", "title": "Steel water bottle",
                "description": "Silver insulated bottle with a black cap and a small scratch near the base.",
                "category": "accessories", "days": 2, "block": "Block B", "floor": "Ground",
                "room": "", "area": "Cafeteria", "status": "available",
                "creator": office_id, "tag": "LL-CVR-" + str(today.year) + "-000002",
                "private": "Small dent on the underside of the base.",
                "value": "low", "sensitivity": 1, "level": 2,
            },
            {
                "public_ref": "LL-R5N2D9", "report_type": "found", "title": "Wireless earbuds case",
                "description": "Black wireless earbud charging case found near the library study area.",
                "category": "accessories", "days": 1, "block": "Block A", "floor": "1",
                "room": "", "area": "Library study area", "status": "available",
                "creator": office_id, "tag": "LL-CVR-" + str(today.year) + "-000003",
                "private": "A tiny white sticker is placed on the back edge of the case.",
                "value": "medium", "sensitivity": 1, "level": 2,
            },
            {
                "public_ref": "LL-C9W4B6", "report_type": "found", "title": "Scientific calculator",
                "description": "Dark scientific calculator in a plain black protective cover.",
                "category": "electronics", "days": 3, "block": "Block C", "floor": "2",
                "room": "C-204", "area": "Classroom corridor", "status": "available",
                "creator": office_id, "tag": "LL-CVR-" + str(today.year) + "-000004",
                "private": "The cover has a small blue fabric tab near the zip.",
                "value": "medium", "sensitivity": 1, "level": 3,
            },
            {
                "public_ref": "LL-U2F6J8", "report_type": "found", "title": "Student identity card",
                "description": "A student identity card was handed to the campus office.",
                "category": "identity_documents", "days": 1, "block": "Block A", "floor": "Ground",
                "room": "", "area": "Reception", "status": "available",
                "creator": office_id, "tag": "LL-CVR-" + str(today.year) + "-000005",
                "private": "Verify against the authorised campus record; do not disclose the card number.",
                "value": "unknown", "sensitivity": 4, "level": 4,
            },
            {
                "public_ref": "LL-H6P1S3", "report_type": "found", "title": "Grey umbrella",
                "description": "Compact grey folding umbrella with a curved handle.",
                "category": "clothing", "days": 0, "block": "Block B", "floor": "Ground",
                "room": "", "area": "Cafeteria entrance", "status": "awaiting_intake",
                "creator": student_id, "tag": None, "private": None,
                "value": "unknown", "sensitivity": 1, "level": None,
            },
        ]
        for item in examples:
            occurred = (today - timedelta(days=item["days"])).isoformat(timespec="minutes")
            conn.execute(
                """INSERT INTO reports(id, public_ref, report_type, title, description, category,
                   occurred_at, location_block, location_floor, location_room, location_area,
                   status, created_by, tag_id, private_detail, value_band, sensitivity_level,
                   verification_level, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    uuid.uuid4().hex, item["public_ref"], item["report_type"], item["title"],
                    item["description"], item["category"], occurred, item["block"], item["floor"],
                    item["room"], item["area"], item["status"], item["creator"], item["tag"],
                    item["private"], item["value"], item["sensitivity"], item["level"], now_iso(), now_iso()
                ),
            )
        conn.execute(
            "UPDATE reports SET storage_location=? WHERE tag_id IS NOT NULL AND (storage_location IS NULL OR TRIM(storage_location)='')",
            ("Demo storage · shelf A-01",),
        )
        conn.execute(
            """INSERT INTO reports(id, public_ref, report_type, title, description, category,
               occurred_at, location_block, location_floor, location_room, location_area,
               status, created_by, created_at, updated_at)
               VALUES (?, ?, 'lost', ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)""",
            (
                "demo-lost-backpack", "LL-MY-1024", "Dark blue backpack",
                "I lost a dark blue backpack with two front pockets around the library.",
                "bags_wallets", (today - timedelta(days=1)).isoformat(timespec="minutes"),
                "Block A", "1", "", "Library", student_id, now_iso(), now_iso()
            ),
        )
