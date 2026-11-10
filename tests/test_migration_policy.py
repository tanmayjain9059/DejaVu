import unittest

from scripts.migrate_sqlite_to_postgres import unsupported_source_tables


class MigrationPolicyTests(unittest.TestCase):
    def test_rebuildable_embedding_cache_is_not_a_migration_blocker(self):
        self.assertEqual(
            unsupported_source_tables({"users", "schema_migrations", "ai_embedding_cache", "public_roll_identities", "public_rate_limits"}),
            set(),
        )

    def test_unknown_source_tables_still_fail_closed(self):
        self.assertEqual(
            unsupported_source_tables({"users", "unrecognised_legacy_table"}),
            {"unrecognised_legacy_table"},
        )


if __name__ == "__main__":
    unittest.main()
