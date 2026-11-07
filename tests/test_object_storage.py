"""Tests for the default local upload backend and safe object keys."""
from __future__ import annotations

import os
import tempfile
from unittest.mock import patch
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import object_storage


class ObjectStorageTests(unittest.TestCase):
    def test_local_backend_round_trips_and_deletes_uploads(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(object_storage.config, "UPLOAD_DIR", Path(directory)), patch.dict(
                os.environ,
                {
                    "OBJECT_STORAGE_BUCKET": "",
                    "OBJECT_STORAGE_ENDPOINT_URL": "",
                    "OBJECT_STORAGE_ACCESS_KEY_ID": "",
                    "OBJECT_STORAGE_SECRET_ACCESS_KEY": "",
                },
            ):
                object_storage.store_upload("report-test.jpg", b"image-bytes")
                self.assertEqual(object_storage.read_upload("report-test.jpg"), b"image-bytes")
                object_storage.delete_upload("report-test.jpg")
                with self.assertRaises(FileNotFoundError):
                    object_storage.read_upload("report-test.jpg")

    def test_s3_backend_round_trips_through_private_bucket(self):
        class FakeBody:
            def read(self):
                return b"remote-image"

        class FakeS3:
            def __init__(self):
                self.objects = {}
                self.put_args = None

            def put_object(self, **kwargs):
                self.put_args = kwargs
                self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

            def get_object(self, **kwargs):
                return {"Body": FakeBody()}

            def delete_object(self, **kwargs):
                self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)

        client = FakeS3()
        remote_env = {
            "OBJECT_STORAGE_BUCKET": "private-lostlink",
            "OBJECT_STORAGE_ENDPOINT_URL": "https://account.r2.cloudflarestorage.com",
            "OBJECT_STORAGE_ACCESS_KEY_ID": "test-access",
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": "test-secret",
            "OBJECT_STORAGE_REGION": "auto",
        }
        with patch.dict(os.environ, remote_env), patch.object(object_storage, "_s3_client", return_value=client):
            object_storage.store_upload("report-test.jpg", b"remote-image")
            self.assertEqual(client.put_args["ContentType"], "image/jpeg")
            self.assertEqual(client.put_args["CacheControl"], "private, no-store")
            self.assertEqual(object_storage.read_upload("report-test.jpg"), b"remote-image")
            object_storage.delete_upload("report-test.jpg")
            self.assertNotIn(("private-lostlink", "report-test.jpg"), client.objects)

    def test_s3_client_uses_supabase_compatible_path_style_and_checksum_settings(self):
        import boto3
        remote_env = {
            "OBJECT_STORAGE_BUCKET": "lostlink-private",
            "OBJECT_STORAGE_ENDPOINT_URL": "https://project-ref.storage.supabase.co/storage/v1/s3",
            "OBJECT_STORAGE_ACCESS_KEY_ID": "test-access",
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": "test-secret",
            "OBJECT_STORAGE_REGION": "ap-south-1",
        }
        object_storage._s3_client.cache_clear()
        try:
            with patch.dict(os.environ, remote_env), patch("boto3.client") as client_factory:
                object_storage._s3_client()
                kwargs = client_factory.call_args.kwargs
                self.assertEqual(kwargs["endpoint_url"], remote_env["OBJECT_STORAGE_ENDPOINT_URL"])
                self.assertEqual(kwargs["region_name"], "ap-south-1")
                self.assertEqual(kwargs["config"].s3["addressing_style"], "path")
                self.assertEqual(kwargs["config"].request_checksum_calculation, "when_required")
                self.assertEqual(kwargs["config"].response_checksum_validation, "when_required")
        finally:
            object_storage._s3_client.cache_clear()

    def test_storage_readiness_checks_private_bucket(self):
        class FakeS3:
            def __init__(self):
                self.bucket = None
            def head_bucket(self, **kwargs):
                self.bucket = kwargs["Bucket"]
        client = FakeS3()
        remote_env = {
            "OBJECT_STORAGE_BUCKET": "lostlink-private",
            "OBJECT_STORAGE_ENDPOINT_URL": "https://project-ref.storage.supabase.co/storage/v1/s3",
            "OBJECT_STORAGE_ACCESS_KEY_ID": "test-access",
            "OBJECT_STORAGE_SECRET_ACCESS_KEY": "test-secret",
        }
        with patch.dict(os.environ, remote_env), patch.object(object_storage, "_s3_client", return_value=client):
            self.assertTrue(object_storage.check_object_storage_connection())
            self.assertEqual(client.bucket, "lostlink-private")

    def test_upload_keys_reject_paths(self):
        for key in ("../outside.jpg", "/tmp/image.jpg", "folder/image.jpg", ".."):
            with self.subTest(key=key), self.assertRaises(ValueError):
                object_storage.store_upload(key, b"not-written")

    def test_partial_remote_configuration_fails_closed(self):
        with patch.dict(
            os.environ,
            {
                "OBJECT_STORAGE_BUCKET": "private-bucket",
                "OBJECT_STORAGE_ENDPOINT_URL": "",
                "OBJECT_STORAGE_ACCESS_KEY_ID": "",
                "OBJECT_STORAGE_SECRET_ACCESS_KEY": "",
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "Configure OBJECT_STORAGE"):
                object_storage.object_storage_enabled()


if __name__ == "__main__":
    unittest.main()
