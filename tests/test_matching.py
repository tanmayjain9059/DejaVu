import unittest
import sys
from contextlib import nullcontext
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

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

        ranked = engine.rank(lost, candidates)

        self.assertEqual(fake_model.calls, 1)
        self.assertEqual(len(fake_model.inputs), 3)
        self.assertTrue(all(item["engine"] == "sentence_embeddings" for item in ranked))

    def test_lightweight_comparison_does_not_load_optional_models(self):
        engine = MatchingEngine()
        engine._load_text_model = lambda: self.fail("semantic model should not load")
        engine.image_similarity = lambda *_: self.fail("CLIP should not run")
        report = {"title": "Blue bag", "description": "blue bag", "category": "bags_wallets"}

        result = engine.compare(report, report, use_models=False)

        self.assertEqual(result["engine"], "lexical_baseline")
        self.assertIsNone(result["signals"]["image"])

    def test_rank_searches_candidates_beyond_previous_500_limit(self):
        lost = {
            "title": "Navy backpack", "description": "blue backpack with two front pockets",
            "category": "bags_wallets", "location_block": "Block A",
        }
        candidates = [
            {
                "id": str(index), "title": f"Unrelated item {index}",
                "description": "steel water bottle", "category": "accessories",
            }
            for index in range(550)
        ]
        candidates[0] = {
            "id": "old-best", "title": "Navy backpack",
            "description": "blue backpack with two front pockets", "category": "bags_wallets",
            "location_block": "Block A",
        }

        ranked = self.engine.rank(lost, candidates, limit=5)

        self.assertEqual(ranked[0]["report"]["id"], "old-best")
        self.assertEqual(len(ranked), 5)

    def test_optional_models_only_process_bounded_shortlists(self):
        class FakeModel:
            def __init__(self):
                self.inputs = []

            def encode(self, texts, **kwargs):
                self.inputs = list(texts)
                return [[1.0, 0.0] for _ in texts]

        engine = MatchingEngine()
        fake_model = FakeModel()
        engine.semantic_enabled = True
        engine._text_attempted = True
        engine._text_model = fake_model
        engine.clip_enabled = True
        clip_calls = []
        engine.image_similarity = lambda *_: clip_calls.append(True) or 0.8
        lost = {"title": "Blue backpack", "description": "blue bag with pockets", "category": "bags_wallets"}
        candidates = [
            {"title": f"Candidate {index}", "description": "blue bag with pockets", "category": "bags_wallets"}
            for index in range(550)
        ]

        ranked = engine.rank(lost, candidates, limit=5)

        self.assertEqual(len(ranked), 5)
        self.assertEqual(len(fake_model.inputs), engine.SEMANTIC_RERANK_LIMIT + 1)
        self.assertEqual(len(clip_calls), engine.CLIP_RERANK_LIMIT)


    def test_clip_reads_storage_keys_for_two_uploaded_report_images(self):
        class FakeTensor:
            def __init__(self, values): self.values = values
            def __getitem__(self, index): return FakeTensor(self.values[index])
            def __mul__(self, other): return FakeTensor([a * b for a, b in zip(self.values, other.values)])
            def item(self): return self.values if isinstance(self.values, (int, float)) else sum(self.values)
        fake_torch = SimpleNamespace(
            no_grad=nullcontext,
            nn=SimpleNamespace(functional=SimpleNamespace(normalize=lambda tensor, dim: tensor)),
            sum=lambda tensor: FakeTensor(sum(tensor.values)),
        )
        class FakeProcessor:
            def __call__(self, images=None, **kwargs): return {"pixel_values": object()}
        class FakeModel:
            def get_image_features(self, **kwargs): return FakeTensor([[1.0, 0.0], [1.0, 0.0]])
        image = Image.new("RGB", (8, 8), (30, 90, 150))
        stream = BytesIO(); image.save(stream, format="JPEG")
        image_bytes = stream.getvalue()
        engine = MatchingEngine()
        engine.clip_enabled = True
        engine._clip_attempted = True
        engine._clip_model = FakeModel()
        engine._clip_processor = FakeProcessor()
        with patch.dict(sys.modules, {"torch": fake_torch}), patch(
            "app.matching.read_upload",
            side_effect=lambda key: {"lost-report.jpg": image_bytes, "found-report.jpg": image_bytes}[key],
        ) as read_upload:
            score = engine.image_similarity({"image_path": "lost-report.jpg"}, {"image_path": "found-report.jpg"})
        self.assertEqual(score, 1.0)
        self.assertEqual([call.args[0] for call in read_upload.call_args_list],
                         ["lost-report.jpg", "found-report.jpg"])

    def test_clip_compares_single_photo_with_opposite_report_text(self):
        class FakeTensor:
            def __init__(self, values): self.values = values
            def __getitem__(self, index): return FakeTensor(self.values[index])
            def __mul__(self, other): return FakeTensor([a * b for a, b in zip(self.values, other.values)])
            def item(self): return self.values if isinstance(self.values, (int, float)) else sum(self.values)
        fake_torch = SimpleNamespace(
            no_grad=nullcontext,
            nn=SimpleNamespace(functional=SimpleNamespace(normalize=lambda tensor, dim: tensor)),
            sum=lambda tensor: FakeTensor(sum(tensor.values)),
        )
        class FakeProcessor:
            def __call__(self, images=None, text=None, **kwargs):
                if images is not None: return {"pixel_values": object()}
                return {"input_ids": object(), "attention_mask": object()}
        class FakeModel:
            def get_image_features(self, **kwargs): return FakeTensor([[1.0, 0.0]])
            def get_text_features(self, **kwargs): return FakeTensor([[1.0, 0.0]])
        image = Image.new("RGB", (8, 8), (30, 90, 150))
        stream = BytesIO(); image.save(stream, format="JPEG")
        image_bytes = stream.getvalue()
        engine = MatchingEngine()
        engine.clip_enabled = True
        engine._clip_attempted = True
        engine._clip_model = FakeModel()
        engine._clip_processor = FakeProcessor()
        def read(key):
            if key == "found-report.jpg": return image_bytes
            raise FileNotFoundError(key)
        with patch.dict(sys.modules, {"torch": fake_torch}), patch("app.matching.read_upload", side_effect=read) as read_upload:
            score = engine.image_similarity(
                {"title": "Blue backpack", "description": "two front pockets"},
                {"image_path": "found-report.jpg"},
            )
        self.assertEqual(score, 1.0)
        self.assertEqual([call.args[0] for call in read_upload.call_args_list], ["found-report.jpg"])

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
