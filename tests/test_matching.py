import unittest

from app.matching import MatchingEngine, lexical_similarity


class MatchingTests(unittest.TestCase):
    def setUp(self):
        self.engine = MatchingEngine()

    def test_same_description_scores_above_unrelated_description(self):
        same = lexical_similarity(
            "Navy backpack with two front pockets",
            "Dark blue backpack with two front pockets"
        )
        different = lexical_similarity(
            "Navy backpack with two front pockets",
            "Steel water bottle with a black cap"
        )
        self.assertGreater(same, different)

    def test_category_location_and_date_affect_match(self):
        lost = {
            "title": "Blue backpack", "description": "dark blue bag with two pockets",
            "category": "bags_wallets", "location_block": "Block A",
            "location_floor": "1", "location_room": "A-101",
            "location_area": "Library", "occurred_at": "2026-10-13T12:00:00"
        }
        found = dict(lost)
        result = self.engine.compare(lost, found)
        self.assertGreaterEqual(result["score"], 0.9)
        self.assertIn("category", result["signals"])

    def test_optional_brand_colour_and_visible_features_improve_matching(self):
        lost = {
            "title": "Small accessory", "description": "A small item lost in a classroom",
            "category": "accessories", "brand": "Northline", "primary_color": "teal",
            "visible_features": "two silver clips and a woven loop",
        }
        found_with_details = {
            "title": "Small accessory", "description": "A small item found in a hallway",
            "category": "accessories", "brand": "Northline", "primary_color": "teal",
            "visible_features": "two silver clips and a woven loop",
        }
        found_without_details = {
            "title": "Small accessory", "description": "A small item found in a hallway",
            "category": "accessories",
        }
        detailed_score = self.engine.compare(lost, found_with_details)["score"]
        generic_score = self.engine.compare(lost, found_without_details)["score"]
        self.assertGreater(detailed_score, generic_score)

    def test_missing_location_and_date_are_supported(self):
        lost = {"title": "Black headphones", "description": "black headphones", "category": "accessories"}
        found = {"title": "Black headphones", "description": "black headphones", "category": "accessories"}
        result = self.engine.compare(lost, found)
        self.assertIsNone(result["signals"]["location"])
        self.assertIsNone(result["signals"]["time"])
        self.assertIn("text", result["signals"])

    def test_match_reasons_quote_actual_brand_colour_location_and_time(self):
        lost = {
            "title": "Black Apple headphones", "description": "Black headphones last seen at the Library.",
            "category": "electronics", "brand": "Apple", "primary_color": "black",
            "location_area": "Library", "occurred_at": "2026-10-13T10:00:00",
        }
        found = {
            "title": "Apple wireless headphones", "description": "Black headphones found at the Library.",
            "category": "electronics", "brand": "Apple", "primary_color": "Black",
            "location_area": "Library", "occurred_at": "2026-10-13T12:00:00",
        }
        reasons = " ".join(self.engine.compare(lost, found)["reasons"])
        self.assertIn("Brand matches: Apple", reasons)
        self.assertIn("Colour matches: Black", reasons)
        self.assertIn("Both reports mention Library", reasons)
        self.assertIn("about 2 hours apart", reasons)

    def test_wrong_category_is_explained_with_actual_category_values(self):
        lost = {"title": "Apple headphones", "description": "black wireless earbuds", "category": "electronics", "brand": "Apple"}
        found = {"title": "Black earbuds pouch", "description": "wireless earbud case", "category": "accessories", "brand": "Apple"}
        reasons = " ".join(self.engine.compare(lost, found)["reasons"])
        self.assertIn("Categories differ: Electronics vs Accessories", reasons)

    def test_rank_batches_semantic_embeddings_once(self):
        class FakeModel:
            def __init__(self):
                self.calls = 0
                self.inputs = []

            def encode(self, texts, **kwargs):
                self.calls += 1
                self.inputs = list(texts)
                return [[1.0, 0.0] for _ in texts]

        engine = MatchingEngine()
        fake_model = FakeModel()
        engine.semantic_enabled = True
        engine._text_attempted = True
        engine._text_model = fake_model
        lost = {"title": "Blue bag", "description": "blue bag with pockets", "category": "bags_wallets"}
        candidates = [
            {"title": "Blue backpack", "description": "blue bag with pockets", "category": "bags_wallets"},
            {"title": "Steel bottle", "description": "silver bottle", "category": "accessories"},
        ]

        from unittest.mock import patch
        with patch("app.services.embedding_cache.get_cached_embeddings", return_value={}):
            with patch("app.services.embedding_cache.store_cached_embeddings"):
                ranked = engine.rank(lost, candidates)

        self.assertEqual(fake_model.calls, 1)
        self.assertEqual(len(fake_model.inputs), 3)
        self.assertTrue(all(item["engine"] == "sentence_embeddings" for item in ranked))

    def test_rank_uses_cached_embeddings_without_calling_model(self):
        from unittest.mock import patch
        from app.services.embedding_cache import embedding_cache_key

        lost = {"title": "Blue bag", "description": "blue bag with pockets", "category": "bags_wallets"}
        found = {"title": "Blue backpack", "description": "blue bag with pockets", "category": "bags_wallets"}
        texts = [
            " ".join(str(lost.get(k) or "") for k in (
                "title", "description", "brand", "primary_color", "visible_features",
                "category", "ai_caption", "ai_keywords"
            )),
            " ".join(str(found.get(k) or "") for k in (
                "title", "description", "brand", "primary_color", "visible_features",
                "category", "ai_caption", "ai_keywords"
            )),
        ]
        cached = {
            embedding_cache_key(texts[0]): [1.0, 0.0],
            embedding_cache_key(texts[1]): [1.0, 0.0],
        }

        class FakeModel:
            def encode(self, *_args, **_kwargs):
                self.fail("model should not run when all vectors are cached")

            def fail(self, message):
                raise AssertionError(message)

        engine = MatchingEngine()
        engine.semantic_enabled = True
        engine._text_attempted = True
        engine._text_model = FakeModel()
        with patch("app.services.embedding_cache.get_cached_embeddings", return_value=cached):
            with patch("app.services.embedding_cache.store_cached_embeddings") as store:
                ranked = engine.rank(lost, [found])
        self.assertEqual(ranked[0]["engine"], "sentence_embeddings")
        self.assertEqual(ranked[0]["signals"]["text"], 1.0)
        store.assert_not_called()

    def test_rank_encodes_only_missing_embeddings_and_stores_them(self):
        from unittest.mock import patch
        from app.services.embedding_cache import embedding_cache_key

        lost = {"title": "Blue bag", "description": "blue bag with pockets", "category": "bags_wallets"}
        found = {"title": "Blue backpack", "description": "blue bag with pockets", "category": "bags_wallets"}
        texts = [
            " ".join(str(lost.get(k) or "") for k in (
                "title", "description", "brand", "primary_color", "visible_features",
                "category", "ai_caption", "ai_keywords"
            )),
            " ".join(str(found.get(k) or "") for k in (
                "title", "description", "brand", "primary_color", "visible_features",
                "category", "ai_caption", "ai_keywords"
            )),
        ]

        class FakeModel:
            def __init__(self):
                self.inputs = []

            def encode(self, values, **_kwargs):
                self.inputs = list(values)
                return [[1.0, 0.0] for _ in values]

        model = FakeModel()
        engine = MatchingEngine()
        engine.semantic_enabled = True
        engine._text_attempted = True
        engine._text_model = model
        cached = {embedding_cache_key(texts[0]): [1.0, 0.0]}
        with patch("app.services.embedding_cache.get_cached_embeddings", return_value=cached):
            with patch("app.services.embedding_cache.store_cached_embeddings") as store:
                engine.rank(lost, [found])
        self.assertEqual(model.inputs, [texts[1]])
        store.assert_called_once()
        stored = store.call_args.args[1]
        self.assertEqual(list(stored), [embedding_cache_key(texts[1])])

    def test_lightweight_comparison_does_not_load_optional_models(self):
        engine = MatchingEngine()
        engine._load_text_model = lambda: self.fail("semantic model should not load")
        engine.image_similarity = lambda *_: self.fail("CLIP should not run")
        report = {"title": "Blue bag", "description": "blue bag", "category": "bags_wallets"}

        result = engine.compare(report, report, use_models=False)

        self.assertEqual(result["engine"], "lexical_baseline")
        self.assertIsNone(result["signals"]["image"])

    def test_category_signal_weights_are_normalized_and_category_specific(self):
        from app.matching import category_signal_weights

        electronics = category_signal_weights(
            "electronics", {"text", "image", "category", "location", "time"}
        )
        documents = category_signal_weights(
            "identity_documents", {"text", "image", "category", "location", "time"}
        )
        self.assertAlmostEqual(sum(electronics.values()), 1.0)
        self.assertAlmostEqual(sum(documents.values()), 1.0)
        self.assertGreater(electronics["image"], documents["image"])
        self.assertGreater(documents["text"], electronics["text"])

    def test_category_weights_renormalize_when_image_or_metadata_is_missing(self):
        from app.matching import category_signal_weights

        weights = category_signal_weights("electronics", {"text", "category"})
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        self.assertNotIn("image", weights)
        self.assertNotIn("location", weights)
        self.assertNotIn("time", weights)

    def test_rank_returns_best_candidates_first(self):
        lost = {"title": "Blue backpack", "description": "blue backpack with pockets", "category": "bags_wallets"}
        candidates = [
            {"title": "Steel bottle", "description": "silver bottle", "category": "accessories"},
            {"title": "Blue backpack", "description": "blue bag with pockets", "category": "bags_wallets"},
        ]
        ranked = self.engine.rank(lost, candidates)
        self.assertEqual(ranked[0]["report"]["title"], "Blue backpack")


if __name__ == "__main__":
    unittest.main()
