import os
import unittest
from unittest.mock import patch

from app.services.image_enrichment import _attributes, _keywords, enrich_image


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

    def test_enrichment_is_opt_in_and_disabled_by_default(self):
        with patch.dict(os.environ, {"USE_IMAGE_ENRICHMENT": "false"}):
            result = enrich_image("unused-image.jpg")
        self.assertEqual(result["status"], "disabled")

    def test_unknown_attributes_remain_empty(self):
        self.assertEqual(
            _attributes("An object on a table"),
            {"colours": [], "materials": [], "shapes": []},
        )


if __name__ == "__main__":
    unittest.main()
