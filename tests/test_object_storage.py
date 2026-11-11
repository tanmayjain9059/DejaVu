import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app.services import object_storage


class FakeS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = kwargs["Body"]

    def get_object(self, **kwargs):
        return {"Body": BytesIO(self.objects[(kwargs["Bucket"], kwargs["Key"])])}

    def delete_object(self, **kwargs):
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)

    def head_bucket(self, **kwargs):
        return {}

    def head_object(self, **kwargs):
        if (kwargs["Bucket"], kwargs["Key"]) not in self.objects:
            raise KeyError("missing")


class ObjectStorageTests(unittest.TestCase):
    def test_local_backend_round_trip_and_temporary_materialization(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(object_storage, "UPLOAD_DIR", Path(directory)), \
                 patch.object(object_storage, "_BACKEND", "local"):
                key = object_storage.save_upload("report-photo.jpg", b"private-image")
                self.assertEqual(key, "report-photo.jpg")
                self.assertEqual(object_storage.check_storage_ready(), "local")
                self.assertEqual(object_storage.read_upload(key), b"private-image")
                self.assertTrue(object_storage.upload_exists(key))
                with object_storage.materialize_upload(key) as path:
                    self.assertEqual(path.read_bytes(), b"private-image")
                self.assertEqual(path, Path(directory) / key)
                object_storage.delete_upload(key)
                self.assertFalse(object_storage.upload_exists(key))

    def test_s3_backend_keeps_keys_private_and_supports_round_trip(self):
        fake = FakeS3()
        with patch.object(object_storage, "_BACKEND", "s3"), \
             patch.object(object_storage, "_BUCKET", "private-test-bucket"), \
             patch.object(object_storage, "_PREFIX", "lostlink-private"), \
             patch.object(object_storage, "_s3_client", return_value=fake):
            self.assertEqual(object_storage.check_storage_ready(), "s3")
            key = object_storage.save_upload("claim-proof.jpg", b"private-evidence")
            self.assertEqual(key, "claim-proof.jpg")
            self.assertIn(("private-test-bucket", "lostlink-private/claim-proof.jpg"), fake.objects)
            self.assertEqual(object_storage.read_upload(key), b"private-evidence")
            self.assertTrue(object_storage.upload_exists(key))
            with object_storage.materialize_upload(key) as path:
                self.assertEqual(path.read_bytes(), b"private-evidence")
            self.assertFalse(path.exists())
            object_storage.delete_upload(key)
            self.assertFalse(object_storage.upload_exists(key))

    def test_upload_keys_reject_path_traversal(self):
        for value in ("../secret", "folder/photo.jpg", "folder\\photo.jpg", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    object_storage._validate_key(value)


if __name__ == "__main__":
    unittest.main()
