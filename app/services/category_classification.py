"""Conservative item-category suggestions for LostLink reports.

Uses the already-configured MiniLM sentence model when enabled. A deterministic
keyword baseline keeps the feature usable without downloading another model.
Suggestions are advisory and are never persisted or applied automatically.
"""
from __future__ import annotations

import os
import re
import threading
from typing import Any

from app.core.config import CATEGORY_LABELS

CATEGORY_PROFILES = {
    "stationery": "books notebooks textbook pen pencil stationery calculator ruler geometry set writing supplies",
    "clothing": "shirt jacket sweater hoodie trousers jeans shoes uniform cap scarf clothing apparel",
    "bags_wallets": "backpack bag handbag purse wallet card holder pouch suitcase luggage",
    "accessories": "watch glasses sunglasses jewellery jewelry bracelet necklace ring earbuds headphones",
    "electronics": "mobile phone smartphone laptop tablet charger cable power bank camera computer electronic device",
    "identity_documents": "identity card student ID college ID driving licence passport document certificate debit credit card",
    "keys_access": "keys keychain key ring access card entry card door key locker key",
    "cash_jewellery": "cash money currency coins notes gold silver jewellery jewelry ornament",
    "sports_instruments": "football cricket bat ball racket sports equipment musical instrument guitar violin",
    "other": "miscellaneous personal item object belonging not listed elsewhere",
}
PHRASE_KEYWORDS = {
    "stationery": ("notebook", "textbook", "workbook", "pen", "pencil", "eraser", "calculator", "ruler", "geometry box"),
    "clothing": ("shirt", "jacket", "hoodie", "sweater", "trouser", "jeans", "shoe", "uniform", "cap", "scarf"),
    "bags_wallets": ("backpack", "rucksack", "handbag", "wallet", "purse", "bag", "sling bag"),
    "accessories": ("watch", "glasses", "spectacles", "sunglasses", "earbuds", "headphones", "bracelet", "necklace", "ring"),
    "electronics": ("phone", "mobile", "smartphone", "laptop", "tablet", "charger", "power bank", "camera", "cable"),
    "identity_documents": ("identity card", "student id", "college id", "driving licence", "passport", "debit card", "credit card"),
    "keys_access": ("key", "keys", "keychain", "key ring", "access card", "entry card"),
    "cash_jewellery": ("cash", "money", "currency", "coin", "gold", "silver", "jewellery", "jewelry"),
    "sports_instruments": ("football", "cricket bat", "racket", "sports", "guitar", "violin", "musical instrument"),
}
_MODEL = None
_MODEL_LOCK = threading.Lock()
_MODEL_ATTEMPTED = False


def _normalise(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (text or "").casefold()))


def _keyword_scores(text: str) -> dict[str, float]:
    normalised = " " + _normalise(text) + " "
    scores = {category: 0.0 for category in CATEGORY_LABELS}
    for category, phrases in PHRASE_KEYWORDS.items():
        for phrase in phrases:
            if " " + phrase + " " in normalised:
                scores[category] += 1.0 + (0.25 if " " in phrase else 0.0)
    # A broad object mention is not enough to force the catch-all category.
    return scores


def _load_model():
    global _MODEL, _MODEL_ATTEMPTED
    if os.getenv("USE_SEMANTIC_MODEL", "false").lower() != "true":
        return None
    if _MODEL_ATTEMPTED:
        return _MODEL
    with _MODEL_LOCK:
        if _MODEL_ATTEMPTED:
            return _MODEL
        _MODEL_ATTEMPTED = True
        try:
            from sentence_transformers import SentenceTransformer
            _MODEL = SentenceTransformer(os.getenv(
                "SEMANTIC_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            ))
        except Exception:
            _MODEL = None
    return _MODEL


def suggest_category(report: dict[str, Any]) -> dict[str, Any]:
    """Return ranked category suggestions; callers must require user confirmation."""
    text = " ".join(str(report.get(key) or "") for key in (
        "title", "description", "brand", "primary_color", "visible_features"
    )).strip()
    if len(_normalise(text)) < 3:
        return {"status": "insufficient_input", "category": None, "alternatives": [],
                "engine": "none", "requires_confirmation": True}

    model = _load_model()
    if model is not None:
        try:
            categories = list(CATEGORY_LABELS)
            prototypes = [CATEGORY_PROFILES[key] for key in categories]
            vectors = model.encode([text, *prototypes], normalize_embeddings=True,
                                    show_progress_bar=False, batch_size=16)
            query = vectors[0]
            ranked = sorted(
                ((float(sum(float(a) * float(b) for a, b in zip(query, vector))), key)
                 for key, vector in zip(categories, vectors[1:])),
                reverse=True,
            )
            engine = "minilm_semantic"
        except Exception:
            ranked = []
            engine = "keyword_fallback"
    else:
        ranked = []
        engine = "keyword_fallback"

    if not ranked:
        scores = _keyword_scores(text)
        ranked = sorted(((score, key) for key, score in scores.items()), reverse=True)
    best_score, best_category = ranked[0]
    if best_score <= 0:
        return {"status": "uncertain", "category": None, "alternatives": [],
                "engine": engine, "requires_confirmation": True}
    alternatives = [
        {"category": key, "label": CATEGORY_LABELS[key], "score": round(float(score), 4)}
        for score, key in ranked[:3]
    ]
    return {
        "status": "suggested",
        "category": best_category,
        "label": CATEGORY_LABELS[best_category],
        "alternatives": alternatives,
        "engine": engine,
        "requires_confirmation": True,
    }
