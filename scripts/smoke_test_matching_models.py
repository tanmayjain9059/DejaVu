"""Download/load both optional models and execute one inference per model.

Run with USE_SEMANTIC_MODEL=true and USE_CLIP_MODEL=true after installing
requirements-ml.txt. The generated image is only an inference smoke fixture;
this script does not measure model accuracy.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path

from PIL import Image

from app.matching import MatchingEngine


def main() -> None:
    if os.getenv("USE_SEMANTIC_MODEL", "false").lower() != "true":
        raise SystemExit("Set USE_SEMANTIC_MODEL=true before running this smoke test.")
    if os.getenv("USE_CLIP_MODEL", "false").lower() != "true":
        raise SystemExit("Set USE_CLIP_MODEL=true before running this smoke test.")

    engine = MatchingEngine()
    text_score, text_source = engine.text_similarity(
        "Navy backpack with a yellow zipper and two front pockets",
        "Dark blue rucksack with two front pockets and a yellow zip",
    )
    if text_source != "sentence_embeddings" or not math.isfinite(text_score):
        raise SystemExit("MiniLM did not complete semantic inference: " + text_source)

    with tempfile.TemporaryDirectory(prefix="lostlink-model-smoke-") as temp_dir:
        image_path = Path(temp_dir) / "fixture.jpg"
        Image.new("RGB", (224, 224), (35, 75, 135)).save(image_path, format="JPEG")
        image_score = engine.image_similarity(
            {"image_path": str(image_path)},
            {
                "title": "Blue backpack",
                "description": "A dark blue backpack with a front pocket",
                "category": "bags_wallets",
            },
        )
    if image_score is None or not math.isfinite(image_score):
        raise SystemExit("CLIP did not complete image-to-text inference.")

    print(json.dumps({
        "text_model": text_source,
        "text_smoke_score": round(text_score, 4),
        "image_model": os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32"),
        "image_smoke_score": round(image_score, 4),
        "model_status": engine.model_status(),
        "note": "Inference smoke test only; scores are not accuracy or ownership probabilities.",
    }, indent=2))


if __name__ == "__main__":
    main()
