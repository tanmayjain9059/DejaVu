import os
import unittest
from unittest.mock import patch

from app.services import category_classification as classifier
from app.matching import matching_engine


class CategoryClassificationTests(unittest.TestCase):
    def setUp(self):
        matching_engine._text_model = None
        matching_engine._text_attempted = False
        matching_engine.semantic_enabled = False

    def tearDown(self):
        classifier._MODEL = None
        classifier._MODEL_ATTEMPTED = False

    def test_keyword_fallback_suggests_electronics(self):
        with patch.dict(os.environ, {"USE_SEMANTIC_MODEL": "false"}):
            result = classifier.suggest_category({
                "title": "Lost mobile phone",
                "description": "Black smartphone with a cracked screen and case",
            })
        self.assertEqual(result["status"], "suggested")
        self.assertEqual(result["category"], "electronics")
        self.assertEqual(result["engine"], "keyword_fallback")
        self.assertTrue(result["requires_confirmation"])

    def test_keyword_fallback_suggests_bags(self):
        with patch.dict(os.environ, {"USE_SEMANTIC_MODEL": "false"}):
            result = classifier.suggest_category({
                "title": "Navy backpack",
                "description": "Blue bag with two front pockets",
            })
        self.assertEqual(result["category"], "bags_wallets")

    def test_ambiguous_text_does_not_force_a_category(self):
        with patch.dict(os.environ, {"USE_SEMANTIC_MODEL": "false"}):
            result = classifier.suggest_category({
                "title": "Small item",
                "description": "An object found near the stairs",
            })
        self.assertEqual(result["status"], "uncertain")
        self.assertIsNone(result["category"])

    def test_insufficient_input_is_rejected(self):
        result = classifier.suggest_category({"title": "x", "description": ""})
        self.assertEqual(result["status"], "insufficient_input")
        self.assertIsNone(result["category"])

    def test_keyword_matching_uses_word_boundaries(self):
        scores = classifier._keyword_scores("A keyboard was found")
        self.assertEqual(scores["keys_access"], 0.0)


if __name__ == "__main__":
    unittest.main()
