"""Fail-closed validation for hosted LostLink deployments."""
from __future__ import annotations

import unittest

from app.core.deployment import validate_hosted_configuration


class HostedConfigurationTests(unittest.TestCase):
    def valid_config(self):
        return {
            "app_env": "production",
            "database_url": "postgresql://user:secret@db.example.test:5432/lostlink?sslmode=require",
            "remote_storage_enabled": True,
            "object_storage_endpoint": "https://project-ref.storage.supabase.co/storage/v1/s3",
            "demo_mode": False,
        }

    def test_local_development_keeps_sqlite_and_local_upload_defaults(self):
        validate_hosted_configuration(
            app_env="development",
            database_url="",
            remote_storage_enabled=False,
            object_storage_endpoint="",
            demo_mode=True,
        )

    def test_production_accepts_postgres_and_private_https_storage(self):
        validate_hosted_configuration(**self.valid_config())

    def test_production_rejects_missing_postgres(self):
        values = self.valid_config()
        values["database_url"] = ""
        with self.assertRaisesRegex(RuntimeError, "PostgreSQL DATABASE_URL"):
            validate_hosted_configuration(**values)

    def test_production_rejects_local_upload_fallback(self):
        values = self.valid_config()
        values["remote_storage_enabled"] = False
        with self.assertRaisesRegex(RuntimeError, "private remote object storage"):
            validate_hosted_configuration(**values)

    def test_production_rejects_non_https_object_storage(self):
        values = self.valid_config()
        values["object_storage_endpoint"] = "http://storage.local"
        with self.assertRaisesRegex(RuntimeError, "HTTPS object-storage"):
            validate_hosted_configuration(**values)

    def test_production_rejects_demo_seeding(self):
        values = self.valid_config()
        values["demo_mode"] = True
        with self.assertRaisesRegex(RuntimeError, "DEMO_MODE"):
            validate_hosted_configuration(**values)


if __name__ == "__main__":
    unittest.main()
