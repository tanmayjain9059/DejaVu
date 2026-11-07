import unittest

from app.services.image_enrichment import _attributes, _keywords


class ImageEnrichmentTests(unittest.TestCase):
    def test_keywords_are_deduplicated_and_filtered(self):
        self.assertEqual(
            _keywords("A black backpack with two front pockets and a zipper"),
            ["black", "backpack", "two", "front", "pockets", "zipper"],
        )

    def test_attribute_extraction_only_returns_terms_present_in_caption(self):
        self.assertEqual(
            _attributes("A rectangular black leather wallet"),
            {"colours": ["black"], "materials": ["leather"], "shapes": ["rectangular"]},
        )

    def test_unknown_attributes_remain_empty(self):
        self.assertEqual(
            _attributes("An object on a table"),
            {"colours": [], "materials": [], "shapes": []},
        )


if __name__ == "__main__":
    unittest.main()
