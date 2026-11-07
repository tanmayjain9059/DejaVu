"""Startup validation for deployments that must use durable managed services."""
from __future__ import annotations


def validate_hosted_configuration(
    *,
    app_env: str,
    database_url: str,
    remote_storage_enabled: bool,
    object_storage_endpoint: str,
    demo_mode: bool,
) -> None:
    """Fail closed when a hosted deployment would fall back to ephemeral local data."""
    if app_env != "production":
        return
    if not database_url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("APP_ENV=production requires a PostgreSQL DATABASE_URL.")
    if not remote_storage_enabled:
        raise RuntimeError("APP_ENV=production requires private remote object storage.")
    if not object_storage_endpoint.startswith("https://"):
        raise RuntimeError("APP_ENV=production requires an HTTPS object-storage endpoint.")
    if demo_mode:
        raise RuntimeError("DEMO_MODE must be false in production.")
