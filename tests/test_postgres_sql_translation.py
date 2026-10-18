"""Unit tests for the limited PostgreSQL SQL compatibility layer."""
import re
import unittest

from app.core.database import PostgresCompatConnection


class PostgresSqlTranslationTests(unittest.TestCase):
    def test_postgres_row_supports_named_and_numeric_access(self):
        from app.core.database import PostgresCompatRow

        row = PostgresCompatRow(["id", "count"], [17, 4])
        self.assertEqual(row["count"], 4)
        self.assertEqual(row[0], 17)
        self.assertEqual(row[1], 4)

    def test_positional_parameters_are_translated(self):
        sql, is_lock = PostgresCompatConnection.translate(
            "SELECT id FROM reports WHERE id=? AND status=?"
        )
        self.assertFalse(is_lock)
        self.assertEqual(sql, "SELECT id FROM reports WHERE id=%s AND status=%s")

    def test_insert_or_ignore_becomes_conflict_safe_insert(self):
        sql, is_lock = PostgresCompatConnection.translate(
            "INSERT OR IGNORE INTO notifications(id, user_id) VALUES (?, ?)"
        )
        self.assertFalse(is_lock)
        self.assertEqual(
            sql,
            "INSERT INTO notifications(id, user_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        )

    def test_claim_verification_replace_becomes_update(self):
        sql, is_lock = PostgresCompatConnection.translate(
            """INSERT OR REPLACE INTO claim_verifications
               (claim_id, verifier_user_id, checks_json, verified_at)
               VALUES (?, ?, ?, ?)"""
        )
        self.assertIn("ON CONFLICT (claim_id) DO UPDATE SET", sql)
        self.assertIn("checks_json=EXCLUDED.checks_json", sql)
        self.assertEqual(sql.count("%s"), 4)

    def test_begin_immediate_uses_transaction_scoped_advisory_lock(self):
        sql, is_lock = PostgresCompatConnection.translate("BEGIN IMMEDIATE")
        self.assertTrue(is_lock)
        self.assertEqual(sql, "SELECT pg_advisory_xact_lock(730021)")

    def test_autoincrement_schema_is_converted_to_serial(self):
        ddl = re.sub(
            r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
            "SERIAL PRIMARY KEY",
            "id INTEGER PRIMARY KEY AUTOINCREMENT",
            flags=re.I,
        )
        self.assertEqual(ddl, "id SERIAL PRIMARY KEY")


if __name__ == "__main__":
    unittest.main()
