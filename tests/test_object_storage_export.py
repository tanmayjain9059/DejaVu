"""Tests for exporting private S3-compatible object storage backups."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.export_object_storage import export_bucket


class FakeBody:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


class FakePaginator:
    def paginate(self, **kwargs):
        return [
            {"Contents": [{"Key": "one.jpg"}, {"Key": "two.jpg"}]},
            {"Contents": []},
        ]


class FakeS3:
    def get_paginator(self, name):
        if name != "list_objects_v2":
            raise AssertionError(name)
        return FakePaginator()

    def get_object(self, **kwargs):
        return {"Body": FakeBody((kwargs["Key"] + "-bytes").encode())}


class ObjectStorageExportTests(unittest.TestCase):
    def test_exports_all_objects_to_private_flat_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "export"
            count, total = export_bucket(target, FakeS3(), "lostlink-private")
            self.assertEqual(count, 2)
            self.assertEqual(total, len(b"one.jpg-bytes") + len(b"two.jpg-bytes"))
            self.assertEqual((target / "one.jpg").read_bytes(), b"one.jpg-bytes")
            self.assertEqual((target / "two.jpg").read_bytes(), b"two.jpg-bytes")
            self.assertEqual((target / "one.jpg").stat().st_mode & 0o777, 0o600)

    def test_refuses_nonempty_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "export"
            target.mkdir()
            (target / "existing").write_text("keep")
            with self.assertRaisesRegex(RuntimeError, "must be empty"):
                export_bucket(target, FakeS3(), "lostlink-private")

    def test_rejects_unsafe_remote_object_keys(self):
        class UnsafePaginator:
            def paginate(self, **kwargs):
                return [{"Contents": [{"Key": "../outside"}]}]
        class UnsafeS3(FakeS3):
            def get_paginator(self, name):
                return UnsafePaginator()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                export_bucket(Path(directory) / "export", UnsafeS3(), "lostlink-private")


if __name__ == "__main__":
    unittest.main()
