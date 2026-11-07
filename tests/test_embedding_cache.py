import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from app.services import embedding_cache


class EmbeddingCacheTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """CREATE TABLE ai_embedding_cache (
                model_name TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                dimension INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(model_name, content_hash)
            )"""
        )
        self.connection.commit()

        @contextmanager
        def fake_connect_db():
            yield self.connection
            self.connection.commit()

        self.connect_patch = patch(
            "app.services.embedding_cache.connect_db", side_effect=fake_connect_db
        )
        self.connect_patch.start()

    def tearDown(self):
        self.connect_patch.stop()
        self.connection.close()

    def test_key_is_stable_and_does_not_expose_raw_text(self):
        left = embedding_cache.embedding_cache_key("  blue   backpack ")
        right = embedding_cache.embedding_cache_key("blue backpack")
        self.assertEqual(left, right)
        self.assertNotIn("backpack", left)

    def test_store_and_retrieve_embeddings(self):
        text = "blue backpack with two pockets"
        key = embedding_cache.embedding_cache_key(text)
        embedding_cache.store_cached_embeddings(
            "minilm@test", {key: [0.25, 0.5, 0.75]}
        )
        result = embedding_cache.get_cached_embeddings("minilm@test", [text])
        self.assertEqual(result[key], [0.25, 0.5, 0.75])

    def test_cache_is_namespaced_by_model(self):
        text = "black laptop charger"
        key = embedding_cache.embedding_cache_key(text)
        embedding_cache.store_cached_embeddings("model-a@1", {key: [1.0, 0.0]})
        self.assertEqual(embedding_cache.get_cached_embeddings("model-b@1", [text]), {})

    def test_model_revision_changes_cache_namespace(self):
        with patch.dict("os.environ", {"SEMANTIC_MODEL_REVISION": "revision-2"}):
            name = embedding_cache.cache_model_identifier("sentence-transformers/test")
        self.assertEqual(name, "sentence-transformers/test@revision-2")


if __name__ == "__main__":
    unittest.main()
