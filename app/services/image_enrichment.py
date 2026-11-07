"""Optional BLIP image captioning for report-photo enrichment.

AI output is stored separately from student-authored report fields. The model is
opt-in because its weights are large and may require significant RAM/CPU.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

_MODEL_LOCK = threading.Lock()
_CAPTION_PIPELINE = None
_MODEL_ATTEMPTED = False
STOP_WORDS = {
    "a", "an", "the", "and", "or", "with", "of", "for", "to", "at", "in",
    "on", "is", "are", "this", "that", "it", "there", "image", "photo",
    "picture", "showing", "shows", "visible",
}
COLOURS = {
    "black", "white", "gray", "grey", "silver", "gold", "red", "blue",
    "navy", "green", "yellow", "orange", "purple", "pink", "brown", "beige",
}
MATERIALS = {"metal", "plastic", "leather", "fabric", "wood", "glass", "rubber", "paper"}
SHAPES = {"round", "rectangular", "square", "circular", "oval", "curved", "flat"}


def _load_pipeline():
    global _CAPTION_PIPELINE, _MODEL_ATTEMPTED
    if _MODEL_ATTEMPTED:
        return _CAPTION_PIPELINE
    with _MODEL_LOCK:
        if _MODEL_ATTEMPTED:
            return _CAPTION_PIPELINE
        _MODEL_ATTEMPTED = True
        if os.getenv("USE_IMAGE_ENRICHMENT", "false").lower() != "true":
            return None
        try:
            from transformers import pipeline
            model_name = os.getenv("IMAGE_CAPTION_MODEL", "Salesforce/blip-image-captioning-base")
            _CAPTION_PIPELINE = pipeline("image-to-text", model=model_name)
        except Exception:
            _CAPTION_PIPELINE = None
        return _CAPTION_PIPELINE


def _keywords(caption: str, limit: int = 12) -> list[str]:
    words = re.findall(r"[a-z][a-z0-9-]{2,}", caption.casefold())
    result = []
    for word in words:
        if word not in STOP_WORDS and word not in result:
            result.append(word)
        if len(result) >= limit:
            break
    return result


def _attributes(caption: str) -> dict[str, list[str]]:
    words = set(re.findall(r"[a-z]+", caption.casefold()))
    colours = sorted(words & COLOURS)
    materials = sorted(words & MATERIALS)
    shapes = sorted(words & SHAPES)
    return {"colours": colours, "materials": materials, "shapes": shapes}


def enrich_image(image_path: str | Path | bytes) -> dict[str, Any]:
    """Caption an image when explicitly enabled; accept bytes from private object storage."""
    if os.getenv("USE_IMAGE_ENRICHMENT", "false").lower() != "true":
        return {"status": "disabled", "message": "Image enrichment is disabled."}
    model = _load_pipeline()
    if model is None:
        return {"status": "unavailable", "message": "The image caption model could not be loaded."}
    model_name = os.getenv("IMAGE_CAPTION_MODEL", "Salesforce/blip-image-captioning-base")
    try:
        from io import BytesIO
        from PIL import Image
        source = BytesIO(image_path) if isinstance(image_path, bytes) else image_path
        with Image.open(source) as image:
            output = model(image.convert("RGB"), max_new_tokens=40)
        caption = str(output[0].get("generated_text", "")).strip()
        if not caption:
            return {"status": "unavailable", "message": "The model returned an empty caption."}
        return {
            "status": "completed",
            "caption": caption[:500],
            "keywords": _keywords(caption),
            "attributes": _attributes(caption),
            "model": model_name,
        }
    except Exception:
        return {"status": "unavailable", "message": "Image enrichment inference failed."}
