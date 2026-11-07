"""Explainable candidate ranking for LostLink.

The lightweight baseline works without external APIs. Optional Sentence
Transformers and CLIP models can be enabled for semantic text and visual
similarity. The engine never treats a score as proof of ownership.
"""
from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

SYNONYMS = {
    "backpack": "bag", "rucksack": "bag", "purse": "wallet",
    "handbag": "bag", "satchel": "bag", "flask": "bottle",
    "thermos": "bottle", "earbud": "earbuds", "airpod": "earbuds",
    "headphone": "headphones", "spectacle": "glasses",
    "spectacles": "glasses", "eyeglass": "glasses", "eyeglasses": "glasses",
    "identity": "id", "identification": "id", "cardholder": "wallet",
    "navy": "blue", "bluish": "blue", "grey": "gray", "silver": "gray",
}
STOP_WORDS = {
    "a", "an", "the", "and", "or", "with", "of", "for", "to", "at",
    "in", "on", "near", "my", "i", "it", "is", "was", "were", "has",
    "have", "had", "this", "that", "item", "found", "lost", "around",
}


def tokens(text: str) -> list[str]:
    values = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [SYNONYMS.get(x, x) for x in values if x not in STOP_WORDS]


def lexical_similarity(left: str, right: str) -> float:
    """A deterministic no-network baseline, not a learned semantic model."""
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    jaccard = len(sa & sb) / max(1, len(sa | sb))
    sequence = SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    detail_terms = {"black", "blue", "red", "green", "white", "gray",
                    "gold", "scratch", "sticker", "zipper", "crack",
                    "stain", "stripe", "logo", "pocket", "case"}
    details = (sa & sb) & detail_terms
    detail_overlap = len(details) / max(1, len((sa | sb) & detail_terms))
    return min(1.0, 0.55 * jaccard + 0.30 * sequence + 0.15 * detail_overlap)


def _parse_date(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _text_value(report: dict[str, Any]) -> str:
    # Explicit public characteristics contribute to matching without reusing private claim evidence.
    return " ".join(
        str(report.get(k) or "")
        for k in ("title", "description", "brand", "primary_color", "visible_features", "category", "ai_caption", "ai_keywords")
    )


def _location_score(lost: dict[str, Any], found: dict[str, Any]) -> float | None:
    lb, fb = (lost.get("location_block") or "").strip().lower(), (found.get("location_block") or "").strip().lower()
    lf, ff = (lost.get("location_floor") or "").strip().lower(), (found.get("location_floor") or "").strip().lower()
    lr, fr = (lost.get("location_room") or "").strip().lower(), (found.get("location_room") or "").strip().lower()
    la, fa = (lost.get("location_area") or "").strip().lower(), (found.get("location_area") or "").strip().lower()
    if not any((lb, lf, lr, la)) or not any((fb, ff, fr, fa)):
        return None
    if lr and fr and lr == fr and (not lb or not fb or lb == fb):
        return 1.0
    if lb and fb and lb == fb:
        if lf and ff and lf == ff:
            return 0.88
        return 0.75
    if la and fa and la == fa:
        return 0.8
    if lb and fb and lb != fb:
        return 0.12
    return 0.35


def _time_score(lost: dict[str, Any], found: dict[str, Any]) -> float | None:
    ld, fd = _parse_date(lost.get("occurred_at")), _parse_date(found.get("occurred_at"))
    if not ld or not fd:
        return None
    days = abs((ld - fd).total_seconds()) / 86400
    if days <= 1:
        return 1.0
    if days <= 3:
        return 0.88
    if days <= 7:
        return 0.72
    if days <= 14:
        return 0.55
    if days <= 30:
        return 0.32
    if days <= 60:
        return 0.12
    return 0.0


# Category-aware weights are ranking policy, not separately trained models.
# Values are normalized over the signals available for each report pair.
CATEGORY_SIGNAL_WEIGHTS = {
    "electronics": {"text": 0.34, "image": 0.30, "category": 0.14, "location": 0.12, "time": 0.10},
    "identity_documents": {"text": 0.45, "image": 0.10, "category": 0.15, "location": 0.15, "time": 0.15},
    "bags_wallets": {"text": 0.40, "image": 0.25, "category": 0.15, "location": 0.10, "time": 0.10},
    "clothing": {"text": 0.40, "image": 0.25, "category": 0.15, "location": 0.10, "time": 0.10},
    "accessories": {"text": 0.40, "image": 0.25, "category": 0.15, "location": 0.10, "time": 0.10},
    "keys_access": {"text": 0.35, "image": 0.25, "category": 0.15, "location": 0.15, "time": 0.10},
    "cash_jewellery": {"text": 0.35, "image": 0.30, "category": 0.15, "location": 0.10, "time": 0.10},
    "stationery": {"text": 0.45, "image": 0.15, "category": 0.15, "location": 0.125, "time": 0.125},
    "sports_instruments": {"text": 0.40, "image": 0.25, "category": 0.15, "location": 0.10, "time": 0.10},
    "other": {"text": 0.50, "image": 0.15, "category": 0.15, "location": 0.10, "time": 0.10},
}
DEFAULT_SIGNAL_WEIGHTS = CATEGORY_SIGNAL_WEIGHTS["other"]


def category_signal_weights(category: str | None, available: set[str]) -> dict[str, float]:
    """Return normalized, category-aware weights for only the signals we have."""
    configured = CATEGORY_SIGNAL_WEIGHTS.get(str(category or "").strip().lower(), DEFAULT_SIGNAL_WEIGHTS)
    selected = {name: weight for name, weight in configured.items() if name in available}
    total = sum(selected.values())
    if total <= 0:
        return {}
    return {name: weight / total for name, weight in selected.items()}


class MatchingEngine:
    def __init__(self) -> None:
        self._text_model = None
        self._text_attempted = False
        self._text_lock = threading.Lock()
        self._text_status = "disabled"
        self._text_failure = None
        self._clip_model = None
        self._clip_processor = None
        self._clip_attempted = False
        self._clip_lock = threading.Lock()
        self._clip_status = "disabled"
        self._clip_failure = None
        self.semantic_enabled = os.getenv("USE_SEMANTIC_MODEL", "false").lower() == "true"
        self.clip_enabled = os.getenv("USE_CLIP_MODEL", "false").lower() == "true"
        if self.semantic_enabled:
            self._text_status = "not_loaded"
        if self.clip_enabled:
            self._clip_status = "not_loaded"

    def model_status(self) -> dict[str, dict[str, Any]]:
        """Return safe model diagnostics; never expose exception messages or paths."""
        return {
            "text": {
                "enabled": self.semantic_enabled,
                "state": self._text_status,
                "model": os.getenv("SEMANTIC_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
                "failed": self._text_failure is not None,
            },
            "image": {
                "enabled": self.clip_enabled,
                "state": self._clip_status,
                "model": os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32"),
                "failed": self._clip_failure is not None,
            },
        }

    def _load_text_model(self):
        # Model construction is lazy and protected because first requests can arrive
        # concurrently in FastAPI's worker threadpool.
        with self._text_lock:
            if self._text_attempted:
                return self._text_model
            self._text_attempted = True
            if not self.semantic_enabled:
                self._text_status = "disabled"
                return None
            self._text_status = "loading"
            try:
                from sentence_transformers import SentenceTransformer
                self._text_model = SentenceTransformer(
                    os.getenv("SEMANTIC_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
                )
                self._text_status = "ready"
            except Exception as exc:
                self._text_model = None
                self._text_status = "unavailable"
                self._text_failure = type(exc).__name__
                logger.warning("Semantic model unavailable; using lexical fallback (%s)", type(exc).__name__)
            return self._text_model

    def _encode_texts_cached(self, texts: list[str], model) -> list[list[float]]:
        """Return normalized vectors, loading and persisting only cache misses."""
        from app.services.embedding_cache import (
            cache_model_identifier, embedding_cache_key,
            get_cached_embeddings, store_cached_embeddings,
        )

        model_name = cache_model_identifier(
            os.getenv("SEMANTIC_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        )
        cached = get_cached_embeddings(model_name, texts)
        missing = list(dict.fromkeys(
            text for text in texts if embedding_cache_key(text) not in cached
        ))
        if missing:
            encoded = model.encode(
                missing, normalize_embeddings=True, batch_size=32,
                show_progress_bar=False,
            )
            fresh = {
                embedding_cache_key(text): [float(value) for value in vector]
                for text, vector in zip(missing, encoded)
            }
            cached.update(fresh)
            store_cached_embeddings(model_name, fresh)
        return [cached[embedding_cache_key(text)] for text in texts]

    def text_similarity(self, left: str, right: str) -> tuple[float, str]:
        model = self._load_text_model()
        if model is not None:
            try:
                vectors = self._encode_texts_cached([left, right], model)
                cosine = sum(a * b for a, b in zip(vectors[0], vectors[1]))
                return max(0.0, min(1.0, cosine)), "sentence_embeddings"
            except Exception as exc:
                self._text_model = None
                self._text_status = "unavailable"
                self._text_failure = type(exc).__name__
                logger.warning("Semantic inference failed; using lexical fallback (%s)", type(exc).__name__)
        return lexical_similarity(left, right), "lexical_baseline"

    def _load_clip(self):
        # Keep CLIP initialisation independent from MiniLM so either model can fail safely.
        with self._clip_lock:
            if self._clip_attempted:
                return self._clip_model, self._clip_processor
            self._clip_attempted = True
            if not self.clip_enabled:
                self._clip_status = "disabled"
                return None, None
            self._clip_status = "loading"
            try:
                from transformers import CLIPModel, CLIPProcessor
                model_name = os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32")
                self._clip_processor = CLIPProcessor.from_pretrained(model_name)
                self._clip_model = CLIPModel.from_pretrained(model_name)
                self._clip_model.eval()
                self._clip_status = "ready"
            except Exception as exc:
                self._clip_model = None
                self._clip_processor = None
                self._clip_status = "unavailable"
                self._clip_failure = type(exc).__name__
                logger.warning("CLIP model unavailable; image signal disabled (%s)", type(exc).__name__)
            return self._clip_model, self._clip_processor

    def _clip_cache_namespace(self) -> str:
        from app.services.embedding_cache import cache_model_identifier
        return cache_model_identifier(
            os.getenv("CLIP_MODEL", "openai/clip-vit-base-patch32"),
            "CLIP_MODEL_REVISION",
        )

    def _clip_image_vector(self, image_path: Path, model, processor, torch):
        """Load one image vector from cache or run CLIP inference for that image."""
        import hashlib
        from io import BytesIO
        from app.services.embedding_cache import get_cached_vectors, store_cached_vectors

        raw = image_path.read_bytes()
        content_hash = hashlib.sha256(raw).hexdigest()
        namespace = self._clip_cache_namespace() + ":image"
        cached = get_cached_vectors(namespace, [content_hash])
        if content_hash in cached:
            return torch.tensor(cached[content_hash], dtype=torch.float32)
        with Image.open(BytesIO(raw)) as source:
            pixels = processor(images=source.convert("RGB"), return_tensors="pt")
        with torch.no_grad():
            vector = model.get_image_features(pixel_values=pixels["pixel_values"])
            vector = torch.nn.functional.normalize(vector, dim=-1)[0]
        values = [float(value) for value in vector.detach().cpu().tolist()]
        store_cached_vectors(namespace, {content_hash: values})
        return torch.tensor(values, dtype=torch.float32)

    def _clip_text_vector(self, text: str, model, processor, torch):
        """Load a CLIP text vector from cache or encode and persist it."""
        from app.services.embedding_cache import (
            embedding_cache_key, get_cached_vectors, store_cached_vectors,
        )

        content_hash = embedding_cache_key(text)
        namespace = self._clip_cache_namespace() + ":text"
        cached = get_cached_vectors(namespace, [content_hash])
        if content_hash in cached:
            return torch.tensor(cached[content_hash], dtype=torch.float32)
        inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            vector = model.get_text_features(
                input_ids=inputs["input_ids"],
                attention_mask=inputs.get("attention_mask"),
            )
            vector = torch.nn.functional.normalize(vector, dim=-1)[0]
        values = [float(value) for value in vector.detach().cpu().tolist()]
        store_cached_vectors(namespace, {content_hash: values})
        return torch.tensor(values, dtype=torch.float32)

    def _batch_clip_scores(
        self, lost: dict[str, Any], found_reports: list[dict[str, Any]]
    ) -> list[float | None] | None:
        """Encode unique uncached candidate photos in batches, then score each pair."""
        if not found_reports or not any(
            report.get("image_path") and Path(str(report["image_path"])).is_file()
            for report in [lost, *found_reports]
        ):
            return [None] * len(found_reports)
        model, processor = self._load_clip()
        if model is None or processor is None:
            return [None] * len(found_reports)
        try:
            import hashlib
            from io import BytesIO
            import torch
            from app.services.embedding_cache import (
                embedding_cache_key, get_cached_vectors, store_cached_vectors,
            )

            reports = [lost, *found_reports]
            image_records: dict[str, Path] = {}
            report_image_keys: list[str | None] = []
            for report in reports:
                path_value = report.get("image_path")
                path = Path(str(path_value or ""))
                if not path_value or not path.is_file():
                    report_image_keys.append(None)
                    continue
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                image_records.setdefault(digest, path)
                report_image_keys.append(digest)

            image_namespace = self._clip_cache_namespace() + ":image"
            image_vectors = get_cached_vectors(image_namespace, list(image_records))
            missing_images = [key for key in image_records if key not in image_vectors]
            if missing_images:
                # Bound peak memory: process a maximum of 16 uncached photos per forward pass.
                for offset in range(0, len(missing_images), 16):
                    batch_keys = missing_images[offset:offset + 16]
                    images = []
                    for key in batch_keys:
                        with Image.open(image_records[key]) as source:
                            images.append(source.convert("RGB").copy())
                    pixel_inputs = processor(images=images, return_tensors="pt")
                    with torch.no_grad():
                        encoded = model.get_image_features(pixel_values=pixel_inputs["pixel_values"])
                        encoded = torch.nn.functional.normalize(encoded, dim=-1)
                    fresh = {
                        key: [float(value) for value in vector.detach().cpu().tolist()]
                        for key, vector in zip(batch_keys, encoded)
                    }
                    image_vectors.update(fresh)
                    store_cached_vectors(image_namespace, fresh)

            # Only reports needing image-to-text comparison require CLIP text vectors.
            needed_texts: dict[str, str] = {}
            for index, report in enumerate(found_reports, start=1):
                lost_has_image = report_image_keys[0] is not None
                found_has_image = report_image_keys[index] is not None
                if lost_has_image != found_has_image:
                    text_report = report if lost_has_image else lost
                    text = _text_value(text_report)
                    needed_texts.setdefault(embedding_cache_key(text), text)

            text_namespace = self._clip_cache_namespace() + ":text"
            text_vectors = get_cached_vectors(text_namespace, list(needed_texts))
            missing_text_keys = [key for key in needed_texts if key not in text_vectors]
            if missing_text_keys:
                text_inputs = processor(
                    text=[needed_texts[key] for key in missing_text_keys],
                    return_tensors="pt", padding=True, truncation=True,
                )
                with torch.no_grad():
                    encoded = model.get_text_features(
                        input_ids=text_inputs["input_ids"],
                        attention_mask=text_inputs.get("attention_mask"),
                    )
                    encoded = torch.nn.functional.normalize(encoded, dim=-1)
                fresh = {
                    key: [float(value) for value in vector.detach().cpu().tolist()]
                    for key, vector in zip(missing_text_keys, encoded)
                }
                text_vectors.update(fresh)
                store_cached_vectors(text_namespace, fresh)

            def dot(left: list[float], right: list[float]) -> float:
                return sum(a * b for a, b in zip(left, right))

            query_key = report_image_keys[0]
            scores: list[float | None] = []
            for index, report in enumerate(found_reports, start=1):
                candidate_key = report_image_keys[index]
                if query_key and candidate_key:
                    cosine = dot(image_vectors[query_key], image_vectors[candidate_key])
                elif query_key or candidate_key:
                    text_report = report if query_key else lost
                    text_key = embedding_cache_key(_text_value(text_report))
                    image_key = candidate_key or query_key
                    cosine = dot(image_vectors[image_key], text_vectors[text_key])
                else:
                    scores.append(None)
                    continue
                scores.append(max(0.0, min(1.0, (float(cosine) + 1.0) / 2.0)))
            return scores
        except Exception:
            # Ranking can continue with text/category/location/time if CLIP fails.
            return None

    def image_similarity(self, lost: dict[str, Any], found: dict[str, Any]) -> float | None:
        """Use cached CLIP image-image similarity, or image-text similarity if one photo is absent."""
        model, processor = self._load_clip()
        if model is None or processor is None:
            return None
        lost_path = Path(str(lost.get("image_path") or ""))
        found_path = Path(str(found.get("image_path") or ""))
        lost_has_image = bool(lost.get("image_path")) and lost_path.is_file()
        found_has_image = bool(found.get("image_path")) and found_path.is_file()
        if not lost_has_image and not found_has_image:
            return None
        try:
            import torch
            with torch.no_grad():
                if lost_has_image and found_has_image:
                    left = self._clip_image_vector(lost_path, model, processor, torch)
                    right = self._clip_image_vector(found_path, model, processor, torch)
                    cosine = torch.sum(left * right).item()
                else:
                    image_path = lost_path if lost_has_image else found_path
                    text_report = found if lost_has_image else lost
                    image_vector = self._clip_image_vector(image_path, model, processor, torch)
                    text_vector = self._clip_text_vector(
                        _text_value(text_report), model, processor, torch
                    )
                    cosine = torch.sum(image_vector * text_vector).item()
            return max(0.0, min(1.0, (float(cosine) + 1.0) / 2.0))
        except Exception:
            return None

    def _batch_semantic_scores(
        self, lost: dict[str, Any], found_reports: list[dict[str, Any]]
    ) -> list[tuple[float, str]] | None:
        model = self._load_text_model()
        if model is None or not found_reports:
            return None
        texts = [_text_value(lost), *(_text_value(report) for report in found_reports)]
        try:
            embeddings = self._encode_texts_cached(texts, model)
            query_vector = embeddings[0]
            scores = []
            for vector in embeddings[1:]:
                cosine = float(sum(float(a) * float(b) for a, b in zip(query_vector, vector)))
                scores.append((max(0.0, min(1.0, cosine)), "sentence_embeddings"))
            return scores
        except Exception as exc:
            self._text_model = None
            self._text_status = "unavailable"
            self._text_failure = type(exc).__name__
            logger.warning("Batched semantic inference failed; using lexical fallback (%s)", type(exc).__name__)
            return None

    def compare(
        self,
        lost: dict[str, Any],
        found: dict[str, Any],
        *,
        use_models: bool = True,
        text_result: tuple[float, str] | None = None,
        image_result: tuple[bool, float | None] | None = None,
    ) -> dict[str, Any]:
        if text_result is not None:
            text_score, text_engine = text_result
        elif use_models:
            text_score, text_engine = self.text_similarity(_text_value(lost), _text_value(found))
        else:
            text_score, text_engine = lexical_similarity(_text_value(lost), _text_value(found)), "lexical_baseline"
        if not use_models:
            image_score = None
        elif image_result is not None:
            image_score = image_result[1] if image_result[0] else self.image_similarity(lost, found)
        else:
            image_score = self.image_similarity(lost, found)
        lost_cat, found_cat = lost.get("category"), found.get("category")
        category_score = 1.0 if lost_cat and lost_cat == found_cat else (0.15 if not lost_cat or not found_cat else 0.0)
        location_score = _location_score(lost, found)
        time_score = _time_score(lost, found)

        available_signals = {"text", "category"}
        if image_score is not None:
            available_signals.add("image")
        if location_score is not None:
            available_signals.add("location")
        if time_score is not None:
            available_signals.add("time")
        signal_values = {
            "text": text_score, "image": image_score, "category": category_score,
            "location": location_score, "time": time_score,
        }
        weights = category_signal_weights(lost_cat, available_signals)
        score = sum(signal_values[name] * weight for name, weight in weights.items())

        reasons: list[str] = []

        # Prefer explanations that quote actual values recorded on both reports.
        category_names = {
            "stationery": "Stationery & books", "clothing": "Clothing", "bags_wallets": "Bags & wallets",
            "accessories": "Accessories", "electronics": "Electronics", "identity_documents": "Identity documents",
            "keys_access": "Keys & access cards", "cash_jewellery": "Cash & jewellery",
            "sports_instruments": "Sports equipment & instruments", "other": "Other",
        }
        if lost_cat and found_cat and lost_cat != found_cat:
            left_label = category_names.get(str(lost_cat), str(lost_cat).replace("_", " ").title())
            right_label = category_names.get(str(found_cat), str(found_cat).replace("_", " ").title())
            reasons.append(f"Categories differ: {left_label} vs {right_label}.")

        left_brand = str(lost.get("brand") or "").strip()
        right_brand = str(found.get("brand") or "").strip()
        def normal_brand(value: str) -> str:
            return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
        if left_brand and right_brand:
            if normal_brand(left_brand) == normal_brand(right_brand):
                reasons.append(f"Brand matches: {right_brand}.")
            else:
                reasons.append(f"Reported brands differ: {left_brand} vs {right_brand}.")

        left_colour = str(lost.get("primary_color") or "").strip()
        right_colour = str(found.get("primary_color") or "").strip()
        if left_colour and right_colour:
            if set(tokens(left_colour)) == set(tokens(right_colour)):
                reasons.append(f"Colour matches: {right_colour}.")
            else:
                reasons.append(f"Reported colours differ: {left_colour} vs {right_colour}.")

        def clean_value(value):
            return " ".join(str(value or "").casefold().split())
        left_room, right_room = clean_value(lost.get("location_room")), clean_value(found.get("location_room"))
        left_area, right_area = clean_value(lost.get("location_area")), clean_value(found.get("location_area"))
        left_block, right_block = clean_value(lost.get("location_block")), clean_value(found.get("location_block"))
        left_floor, right_floor = clean_value(lost.get("location_floor")), clean_value(found.get("location_floor"))
        if left_room and right_room and left_room == right_room:
            reasons.append(f"Both reports mention room {str(found.get('location_room')).strip()}.")
        elif left_area and right_area and left_area == right_area:
            reasons.append(f"Both reports mention {str(found.get('location_area')).strip()}.")
        elif left_block and right_block and left_block == right_block:
            label = "Block " + str(found.get("location_block")).strip()
            if left_floor and right_floor and left_floor == right_floor:
                label += ", floor " + str(found.get("location_floor")).strip()
            reasons.append(f"Both reports place the item in {label}.")
        elif location_score is not None and location_score <= 0.2:
            left_place = str(lost.get("location_area") or lost.get("location_block") or "an unspecified location").strip()
            right_place = str(found.get("location_area") or found.get("location_block") or "an unspecified location").strip()
            if left_place != right_place:
                reasons.append(f"Reported locations differ: {left_place} vs {right_place}.")

        left_time, right_time = _parse_date(lost.get("occurred_at")), _parse_date(found.get("occurred_at"))
        if left_time and right_time:
            minutes_apart = int(round(abs((left_time - right_time).total_seconds()) / 60))
            if minutes_apart < 60:
                time_phrase = "within an hour" if minutes_apart < 5 else f"about {minutes_apart} minutes apart"
            elif minutes_apart < 24 * 60:
                hours_apart = int(round(minutes_apart / 60))
                time_phrase = f"about {hours_apart} hour{'s' if hours_apart != 1 else ''} apart"
            else:
                days_apart = int(round(minutes_apart / (24 * 60)))
                time_phrase = f"about {days_apart} day{'s' if days_apart != 1 else ''} apart"
            if minutes_apart <= 24 * 60 or (time_score is not None and time_score <= 0.2):
                reasons.append(f"Reported times are {time_phrase}.")

        left_features = set(tokens(str(lost.get("visible_features") or "")))
        right_features = set(tokens(str(found.get("visible_features") or "")))
        distinctive = {"scratch", "sticker", "zipper", "pocket", "pockets", "stripe", "logo", "crack",
                       "stain", "hinge", "case", "strap", "loop", "mark", "dent", "button", "screen",
                       "corner", "seam", "pattern", "silver", "gold", "white", "black", "blue", "red"}
        shared_features = sorted((left_features & right_features) & distinctive)
        if shared_features:
            reasons.append("Shared visible details: " + ", ".join(shared_features[:3]) + ".")

        if category_score >= 0.9 and not any(reason.startswith("Categories differ:") for reason in reasons):
            reasons.append("Both reports use the same item category.")
        if text_score >= 0.34 and not shared_features and not any(reason.startswith("Brand matches:") for reason in reasons):
            overlap = sorted(word for word in set(tokens(_text_value(lost))) & set(tokens(_text_value(found))) if len(word) >= 4)
            if overlap:
                reasons.append("Shared description terms: " + ", ".join(overlap[:3]) + ".")
            elif text_engine == "sentence_embeddings":
                reasons.append("The descriptions are semantically similar according to sentence embeddings.")
        if image_score is not None and image_score >= 0.70:
            reasons.append("The available photos have visually compatible content (CLIP image similarity).")
        elif image_score is not None and image_score <= 0.30:
            reasons.append("The available photos are visually dissimilar (CLIP image similarity).")
        if not reasons:
            reasons.append("There is limited overlap in recorded details; review the candidate manually.")

        strength = "strong" if score >= 0.72 else ("possible" if score >= 0.45 else "limited")
        engine = text_engine + (" + CLIP" if image_score is not None else "")
        return {
            "score": round(score, 4),
            "strength": strength,
            "reasons": reasons[:5],
            "signals": {
                "text": round(text_score, 4),
                "image": None if image_score is None else round(image_score, 4),
                "category": round(category_score, 4),
                "location": None if location_score is None else round(location_score, 4),
                "time": None if time_score is None else round(time_score, 4),
            },
            "engine": engine,
        }

    def rank(self, lost: dict[str, Any], found_reports: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
        semantic_scores = self._batch_semantic_scores(lost, found_reports)
        clip_scores = self._batch_clip_scores(lost, found_reports) if self.clip_enabled else None
        if self.clip_enabled and clip_scores is None:
            # Do not fall back to per-candidate inference after a batch failure.
            clip_scores = [None] * len(found_reports)
        ranked = []
        for index, report in enumerate(found_reports):
            text_result = semantic_scores[index] if semantic_scores is not None else None
            image_result = (True, clip_scores[index]) if clip_scores is not None else None
            result = self.compare(
                lost, report, text_result=text_result, image_result=image_result
            )
            ranked.append({"report": report, **result})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:limit]


matching_engine = MatchingEngine()
