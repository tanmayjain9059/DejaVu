#!/usr/bin/env python3
"""Exercise the real pretrained CLIP model on image-image and image-text inputs.

This is an integration smoke test, not a visual-retrieval quality benchmark.
It uses in-memory synthetic images and never writes test files to user storage.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from io import BytesIO
from unittest.mock import patch

from PIL import Image, ImageDraw


def sample_image(background: tuple[int, int, int], accent: tuple[int, int, int]) -> bytes:
    image = Image.new("RGB", (224, 224), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((42, 35, 182, 190), radius=22, fill=accent)
    draw.rectangle((68, 58, 156, 78), fill=(245, 245, 245))
    draw.line((112, 80, 112, 165), fill=(20, 20, 20), width=7)
    stream = BytesIO()
    image.save(stream, format="JPEG", quality=90)
    return stream.getvalue()


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    import torch
    from app.matching import MatchingEngine

    torch.set_num_threads(2)
    engine = MatchingEngine()
    engine.clip_enabled = True
    lost_image = sample_image((25, 60, 120), (15, 100, 190))
    found_image = sample_image((25, 60, 120), (15, 100, 190))
    image_store = {"lost-smoke.jpg": lost_image, "found-smoke.jpg": found_image}

    def read_test_image(key: str) -> bytes:
        try:
            return image_store[key]
        except KeyError as exc:
            raise FileNotFoundError(key) from exc

    with patch("app.matching.read_upload", side_effect=read_test_image):
        image_image_score = engine.image_similarity(
            {"image_path": "lost-smoke.jpg"},
            {"image_path": "found-smoke.jpg"},
        )
        image_text_score = engine.image_similarity(
            {"title": "Blue backpack", "description": "Blue backpack with a front pocket"},
            {"image_path": "found-smoke.jpg"},
        )

    if image_image_score is None or image_text_score is None:
        raise SystemExit("CLIP did not return both image-image and image-text scores.")
    for name, score in (
        ("image-image", image_image_score),
        ("image-text", image_text_score),
    ):
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise SystemExit(f"CLIP returned an invalid {name} score: {score!r}")

    print(
        "Pretrained CLIP inference OK: "
        f"model={__import__('os').getenv('CLIP_MODEL', 'openai/clip-vit-base-patch32')}, "
        f"image_image={image_image_score:.4f}, image_text={image_text_score:.4f}"
    )


if __name__ == "__main__":
    main()
