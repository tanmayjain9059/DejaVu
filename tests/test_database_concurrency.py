"""Concurrent database uniqueness regressions for idempotent event writes."""
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.core import database


@unittest.skipIf(os.getenv("TEST_WITH_POSTGRES", "").lower() == "true",
                 "These file-lock concurrency tests target isolated SQLite; PostgreSQL has a separate integration job.")
class DatabaseConcurrencyConstraintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_values = {
            "DB_PATH": database.DB_PATH,
            "DATA_DIR": database.DATA_DIR,
            "UPLOAD_DIR": database.UPLOAD_DIR,
            "DATABASE_URL": database.DATABASE_URL,
            "DEMO_MODE": database.DEMO_MODE,
        }
        root = Path(self.temp.name)
        database.DB_PATH = root / "concurrency.sqlite"
        database.DATA_DIR = root
        database.UPLOAD_DIR = root / "uploads"
        database.DATABASE_URL = ""
        database.DEMO_MODE = False
        database.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        database.initialise_db()
        with database.connect_db() as conn:
            conn.execute(
                """INSERT INTO users(email, display_name, role, password_hash, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                ("concurrency@example.test", "Concurrency Test", "student",
                 database.hash_password("test-password"), database.now_iso()),
            )
            self.user_id = conn.execute(
                "SELECT id FROM users WHERE email=?", ("concurrency@example.test",)
            ).fetchone()["id"]

    def tearDown(self):
        for name, value in self.old_values.items():
            setattr(database, name, value)
        self.temp.cleanup()

    def _concurrent_idempotent_insert(self, table, event_key, count=12):
        barrier = threading.Barrier(count)

        def insert(index):
            barrier.wait(timeout=5)
            with database.connect_db() as conn:
                if table == "notifications":
                    conn.execute(
                        """INSERT OR IGNORE INTO notifications
                           (id, user_id, event_key, title, message, entity_type, entity_id, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (f"notification-{index}", self.user_id, event_key, "Test", "Test",
                         "test", "entity-1", database.now_iso()),
                    )
                elif table == "reward_ledger":
                    conn.execute(
                        """INSERT OR IGNORE INTO reward_ledger
                           (id, user_id, event_key, points, reason, report_id, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (f"reward-{index}", self.user_id, event_key, 5, "concurrency test",
                         None, database.now_iso()),
                    )
                else:
                    raise AssertionError(f"Unexpected table: {table}")

        with ThreadPoolExecutor(max_workers=count) as pool:
            list(pool.map(insert, range(count)))
        with database.connect_db() as conn:
            return conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE user_id=? AND event_key=?",
                (self.user_id, event_key),
            ).fetchone()[0]

    def test_concurrent_notification_event_is_recorded_once(self):
        self.assertEqual(
            self._concurrent_idempotent_insert("notifications", "same-notification-event"),
            1,
        )

    def test_concurrent_reward_event_is_recorded_once(self):
        self.assertEqual(
            self._concurrent_idempotent_insert("reward_ledger", "same-reward-event"),
            1,
        )


if __name__ == "__main__":
    unittest.main()
