"""Tests for restoring private upload archives into object storage."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.import_object_storage import import_directory


class ObjectStorageImportTests(unittest.TestCase):
    def test_dry_run_validates_files_without_uploading(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "one.jpg").write_bytes(b"one")
            (source / "two.jpg").write_bytes(b"second")
            with patch("scripts.import_object_storage.store_upload") as upload:
                self.assertEqual(import_directory(source), (2, 9))
                upload.assert_not_called()

    def test_execute_uploads_all_files_with_original_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "one.jpg").write_bytes(b"one")
            with patch("scripts.import_object_storage.store_upload") as upload:
                self.assertEqual(import_directory(source, execute=True), (1, 3))
                upload.assert_called_once_with("one.jpg", b"one")

    def test_rejects_unsafe_keys_and_nested_files(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "folder").mkdir()
            with self.assertRaisesRegex(RuntimeError, "Unexpected non-file"):
                import_directory(source)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "../unsafe").write_text("bad")
            with self.assertRaises(ValueError):
                import_directory(source)


if __name__ == "__main__":
    unittest.main()
