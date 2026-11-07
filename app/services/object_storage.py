"""Private upload storage with local and S3-compatible backends.

Database rows store opaque upload keys, never public object URLs. S3 objects remain
private; every read passes through the authenticated application routes.
"""
from __future__ import annotations

import os
import tempfile
from botocore.config import Config
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import UPLOAD_DIR

_BACKEND = os.getenv("UPLOAD_STORAGE_BACKEND", "local").strip().lower()
_BUCKET = os.getenv("S3_BUCKET", "").strip()
_PREFIX = os.getenv("S3_PREFIX", "lostlink-private").strip("/")
_ENDPOINT = os.getenv("S3_ENDPOINT_URL", "").strip() or None
_REGION = os.getenv("S3_REGION", "").strip() or None
_ACCESS_KEY = os.getenv("S3_ACCESS_KEY_ID", "").strip() or None
_SECRET_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "").strip() or None


def storage_backend() -> str:
    if _BACKEND not in {"local", "s3"}:
        raise RuntimeError("UPLOAD_STORAGE_BACKEND must be either 'local' or 's3'.")
    if _BACKEND == "s3" and not _BUCKET:
        raise RuntimeError("S3_BUCKET is required when UPLOAD_STORAGE_BACKEND=s3.")
    return _BACKEND


def _validate_key(key: str) -> str:
    value = str(key or "").strip()
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError("Invalid upload key.")
    if len(value) > 180:
        raise ValueError("Upload key is too long.")
    return value


def _local_path(key: str) -> Path:
    safe_key = _validate_key(key)
    root = UPLOAD_DIR.resolve()
    path = (root / safe_key).resolve()
    if path.parent != root:
        raise ValueError("Upload path escaped the configured storage directory.")
    return path


def _s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError(
            "S3 storage is configured but boto3 is not installed. Install requirements.txt."
        ) from exc
    options = {}
    if _ENDPOINT:
        options["endpoint_url"] = _ENDPOINT
    if _REGION:
        options["region_name"] = _REGION
    if _ACCESS_KEY and _SECRET_KEY:
        options["aws_access_key_id"] = _ACCESS_KEY
        options["aws_secret_access_key"] = _SECRET_KEY
    return boto3.client("s3", config=Config(signature_version="s3v4", s3={"addressing_style": "path"}), **options)


def _object_key(key: str) -> str:
    safe_key = _validate_key(key)
    return f"{_PREFIX}/{safe_key}" if _PREFIX else safe_key


def save_upload(key: str, content: bytes) -> str:
    """Persist bytes privately and return the opaque database key."""
    safe_key = _validate_key(key)
    backend = storage_backend()
    if backend == "local":
        _local_path(safe_key).write_bytes(content)
    else:
        _s3_client().put_object(
            Bucket=_BUCKET,
            Key=_object_key(safe_key),
            Body=content,
            ContentType="image/jpeg",
            ServerSideEncryption="AES256",
        )
    return safe_key


def read_upload(key: str) -> bytes:
    safe_key = _validate_key(key)
    if storage_backend() == "local":
        path = _local_path(safe_key)
        if not path.is_file():
            raise FileNotFoundError(safe_key)
        return path.read_bytes()
    try:
        response = _s3_client().get_object(Bucket=_BUCKET, Key=_object_key(safe_key))
    except Exception as exc:
        error_code = str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            raise FileNotFoundError(safe_key) from exc
        raise
    try:
        return response["Body"].read()
    finally:
        response["Body"].close()


def delete_upload(key: str) -> None:
    safe_key = _validate_key(key)
    if storage_backend() == "local":
        _local_path(safe_key).unlink(missing_ok=True)
    else:
        _s3_client().delete_object(Bucket=_BUCKET, Key=_object_key(safe_key))


def upload_exists(key: str) -> bool:
    try:
        if storage_backend() == "local":
            return _local_path(key).is_file()
        _s3_client().head_object(Bucket=_BUCKET, Key=_object_key(key))
        return True
    except Exception:
        return False


@contextmanager
def materialize_upload(key: str) -> Iterator[Path]:
    """Yield a local path for PIL/CLIP; S3 objects use a short-lived temp file."""
    safe_key = _validate_key(key)
    if storage_backend() == "local":
        path = _local_path(safe_key)
        if not path.is_file():
            raise FileNotFoundError(safe_key)
        yield path
        return
    handle = tempfile.NamedTemporaryFile(prefix="lostlink-", suffix=".jpg", delete=False)
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(read_upload(safe_key))
        yield temp_path
    finally:
        temp_path.unlink(missing_ok=True)


def migrate_local_uploads_to_s3(keys: list[str], *, dry_run: bool = True) -> dict[str, int]:
    """Copy existing local files to the configured private bucket without deleting originals."""
    if storage_backend() != "s3":
        raise RuntimeError("Set UPLOAD_STORAGE_BACKEND=s3 before running the object migration.")
    copied = 0
    missing = 0
    for key in sorted(set(_validate_key(value) for value in keys)):
        source = _local_path(key)
        if not source.is_file():
            missing += 1
            continue
        if not dry_run:
            source_bytes = source.read_bytes()
            save_upload(key, source_bytes)
            # Verify destination bytes before reporting a successful copy.
            if read_upload(key) != source_bytes:
                raise IOError(f"Object-storage verification failed for upload key {key!r}.")
        copied += 1
    return {"copied": copied, "missing": missing}
