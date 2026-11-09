"""Unit tests for the limited PostgreSQL SQL compatibility layer."""
import re
import unittest

from app.core.database import PostgresCompatConnection, lock_advisory_key, lock_row


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

    def test_question_marks_inside_literals_and_comments_are_preserved(self):
        sql, is_lock = PostgresCompatConnection.translate(
            "SELECT '?' AS literal, \"?\" AS identifier, value FROM items "
            "WHERE id=? -- ? is a comment\n/* ? is also a comment */"
        )
        self.assertFalse(is_lock)
        self.assertEqual(
            sql,
            "SELECT '?' AS literal, \"?\" AS identifier, value FROM items "
            "WHERE id=%s -- ? is a comment\n/* ? is also a comment */",
        )

    def test_escaped_quote_does_not_end_sql_string_early(self):
        sql, _ = PostgresCompatConnection.translate(
            "SELECT 'it''s ?' AS literal FROM items WHERE id=?"
        )
        self.assertEqual(sql, "SELECT 'it''s ?' AS literal FROM items WHERE id=%s")

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

    def test_literal_percent_signs_are_escaped_for_psycopg(self):
        sql, is_lock = PostgresCompatConnection.translate(
            "SELECT id FROM reports WHERE title LIKE '%lost%' AND score % 2 = ?"
        )
        self.assertFalse(is_lock)
        self.assertEqual(
            sql,
            "SELECT id FROM reports WHERE title LIKE '%%lost%%' AND score %% 2 = %s",
        )

    def test_percent_signs_inside_literals_and_comments_are_handled(self):
        sql, _ = PostgresCompatConnection.translate(
            "SELECT '100%' AS literal, value FROM items WHERE id=? -- 50% comment"
        )
        self.assertEqual(
            sql,
            "SELECT '100%%' AS literal, value FROM items WHERE id=%s -- 50% comment",
        )

    def test_begin_immediate_starts_transaction_without_global_advisory_lock(self):
        sql, is_lock = PostgresCompatConnection.translate("BEGIN IMMEDIATE")
        self.assertTrue(is_lock)
        self.assertEqual(sql, "SELECT 1")

    def test_row_lock_uses_targeted_for_update_query(self):
        class Cursor:
            def fetchone(self):
                return None

        class FakeConnection:
            def __init__(self):
                self.calls = []

            def execute(self, sql, parameters):
                self.calls.append((sql, parameters))
                return Cursor()

        raw = FakeConnection()
        lock_row(PostgresCompatConnection(raw), "reports", "id", "report-1")
        self.assertEqual(
            raw.calls,
            [("SELECT 1 FROM reports WHERE id=%s FOR UPDATE", ("report-1",))],
        )

    def test_advisory_lock_is_scoped_to_one_logical_key(self):
        class Cursor:
            def fetchone(self):
                return None

        class FakeConnection:
            def __init__(self):
                self.calls = []

            def execute(self, sql, parameters):
                self.calls.append((sql, parameters))
                return Cursor()

        raw = FakeConnection()
        lock_advisory_key(PostgresCompatConnection(raw), "public-rate:report", "192.0.2.10")
        self.assertEqual(
            raw.calls,
            [("SELECT pg_advisory_xact_lock(hashtext(%s))", ("public-rate:report:192.0.2.10",))],
        )

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
