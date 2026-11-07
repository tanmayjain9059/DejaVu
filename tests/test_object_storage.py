"""Tests for the default local upload backend and safe object keys."""
from __future__ import annotations

import os
import tempfile
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
