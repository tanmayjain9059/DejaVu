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


def get_cached_vectors(model_name: str, content_hashes: list[str]) -> dict[str, list[float]]:
    """Fetch vectors by opaque content hashes; failures degrade to cache misses."""
    keys = list(dict.fromkeys(str(key) for key in content_hashes if key))
    if not keys:
        return {}
    placeholders = ",".join("?" for _ in keys)
    try:
        with connect_db() as conn:
            rows = conn.execute(
                f"""SELECT content_hash, embedding_json, dimension FROM ai_embedding_cache
                    WHERE model_name=? AND content_hash IN ({placeholders})""",
                [model_name, *keys],
            ).fetchall()
        result = {}
        for row in rows:
            try:
                vector = json.loads(row["embedding_json"])
                dimension = int(row["dimension"])
                if (isinstance(vector, list) and len(vector) == dimension and dimension > 0
                        and all(isinstance(value, (int, float)) for value in vector)):
                    result[row["content_hash"]] = [float(value) for value in vector]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return result
    except Exception:
        return {}


def get_cached_embeddings(model_name: str, texts: list[str]) -> dict[str, list[float]]:
    """Fetch text vectors using SHA-256 keys derived from normalized text."""
    keys = [embedding_cache_key(text) for text in texts]
    return get_cached_vectors(model_name, keys)

def store_cached_vectors(model_name: str, vectors: dict[str, list[float]]) -> None:
    """Upsert vectors under opaque hashes; raw source content is never persisted."""
    if not vectors:
        return
    timestamp = now_iso()
    try:
        with connect_db() as conn:
            for content_hash, vector in vectors.items():
                if not content_hash or not vector:
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
            conn.execute(
                """DELETE FROM ai_embedding_cache
                   WHERE model_name=? AND content_hash NOT IN (
                     SELECT content_hash FROM ai_embedding_cache
                     WHERE model_name=? ORDER BY updated_at DESC LIMIT ?
                   )""",
                (model_name, model_name, MAX_CACHE_ROWS),
            )
    except Exception:
        return


def store_cached_embeddings(model_name: str, embeddings: dict[str, list[float]]) -> None:
    """Store text vectors; keys are hashes, not raw report text."""
    store_cached_vectors(model_name, embeddings)

def cache_model_identifier(model_name: str, revision_env: str = "SEMANTIC_MODEL_REVISION") -> str:
    """Include an explicit revision so deployments can invalidate stale vectors."""
    revision = os.getenv(revision_env, "default").strip() or "default"
    return f"{model_name}@{revision}"
