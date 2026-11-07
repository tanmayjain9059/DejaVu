"""Persistent, model-versioned cache for public report text embeddings."""
from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from app.core.database import connect_db, now_iso

MAX_CACHE_ROWS = 20000


def normalise_embedding_text(text: str) -> str:
    return " ".join(str(text or "").split())


def embedding_cache_key(text: str) -> str:
    canonical = normalise_embedding_text(text)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get_cached_embeddings(model_name: str, texts: list[str]) -> dict[str, list[float]]:
    """Fetch only requested embeddings; database failures degrade to cache misses."""
    keys = list(dict.fromkeys(embedding_cache_key(text) for text in texts))
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    try:
        with connect_db() as conn:
            rows = conn.execute(
                f"""SELECT content_hash, embedding_json FROM ai_embedding_cache
                    WHERE model_name=? AND content_hash IN ({placeholders})""",
                [model_name, *keys],
            ).fetchall()
        result = {}
        for row in rows:
            try:
                vector = json.loads(row["embedding_json"])
                if isinstance(vector, list) and vector and all(
                    isinstance(value, (int, float)) for value in vector
                ):
                    result[row["content_hash"]] = [float(value) for value in vector]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result
    except Exception:
        # A cache outage must never prevent the lexical or live-model path.
        return {}


def store_cached_embeddings(
    model_name: str, embeddings: dict[str, list[float]]
) -> None:
    """Upsert freshly generated vectors. Keys are hashes, not raw report text."""
    if not embeddings:
        return
    timestamp = now_iso()
    try:
        with connect_db() as conn:
            for content_hash, vector in embeddings.items():
                if not vector:
                    continue
                conn.execute(
                    """INSERT INTO ai_embedding_cache
                       (model_name, content_hash, embedding_json, dimension, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(model_name, content_hash) DO UPDATE SET
                         embedding_json=excluded.embedding_json,
                         dimension=excluded.dimension,
                         updated_at=excluded.updated_at""",
                    (model_name, content_hash, json.dumps(vector, separators=(",", ":")),
                     len(vector), timestamp, timestamp),
                )
            # Keep the cache bounded; the newest 20,000 entries survive.
            conn.execute(
                """DELETE FROM ai_embedding_cache
                   WHERE model_name=? AND content_hash NOT IN (
                     SELECT content_hash FROM ai_embedding_cache
                     WHERE model_name=? ORDER BY updated_at DESC LIMIT ?
                   )""",
                (model_name, model_name, MAX_CACHE_ROWS),
            )
    except Exception:
        # The caller already has the in-memory vectors and can continue.
        return


def cache_model_identifier(model_name: str) -> str:
    """Include an optional explicit revision so deployments can invalidate stale vectors."""
    revision = os.getenv("SEMANTIC_MODEL_REVISION", "default").strip() or "default"
    return f"{model_name}@{revision}"
