"""FastAPI application composition root for LostLink."""
from __future__ import annotations
from contextlib import asynccontextmanager
import os
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from app.core.config import *
from app.core.database import *
from app.core.images import *
from app.core.security import *
from app.core.runtime import *
from app.schemas import *
from app.services.object_storage import check_storage_ready, storage_backend
from app.api.routes.auth import router as auth_router
from app.api.routes.reports import router as reports_router
from app.api.routes.claims import router as claims_router
from app.api.routes.engagement import router as engagement_router
from app.api.routes.public_workflow import router as public_workflow_router, ensure_public_schema

if not SESSION_SECRET or SESSION_SECRET in {
    "replace-with-a-long-random-secret-before-running",
    "local-development-only-change-this",
} or len(SESSION_SECRET) < 32:
    raise RuntimeError("SESSION_SECRET must be a unique, non-placeholder secret of at least 32 characters.")

if HTTPS_ONLY and "*" in ALLOWED_HOSTS:
    raise RuntimeError("ALLOWED_HOSTS must explicitly list canonical hostnames when HTTPS_ONLY is enabled.")
if HTTPS_ONLY and not REQUIRE_REQUEST_ORIGIN:
    raise RuntimeError("REQUIRE_REQUEST_ORIGIN=true is required when HTTPS_ONLY is enabled.")
if AUTH_PROVIDER not in {"local", "supabase"}:
    raise RuntimeError("AUTH_PROVIDER must be either 'local' or 'supabase'.")
if AUTH_PROVIDER == "supabase":
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required for Supabase Auth.")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must point to Supabase PostgreSQL when AUTH_PROVIDER=supabase.")
    if DEMO_MODE:
        raise RuntimeError("DEMO_MODE must be false when Supabase Auth is enabled.")
    if UPLOAD_STORAGE_BACKEND != "s3":
        raise RuntimeError("Supabase Auth deployments must use private S3-compatible object storage.")
    if not FRONTEND_ORIGINS:
        raise RuntimeError("FRONTEND_ORIGINS must contain the exact deployed Vercel origin.")
    if not ALLOWED_EMAIL_DOMAINS:
        raise RuntimeError("ALLOWED_EMAIL_DOMAINS must list the institution-approved email domains.")
    if not OFFICE_USER_EMAILS:
        raise RuntimeError("OFFICE_USER_EMAILS must list at least one explicitly authorised office account.")
    if any(email.rsplit("@", 1)[-1] not in ALLOWED_EMAIL_DOMAINS for email in OFFICE_USER_EMAILS):
        raise RuntimeError("Every OFFICE_USER_EMAILS entry must belong to an allowed email domain.")
    if "*" in ALLOWED_HOSTS:
        raise RuntimeError("ALLOWED_HOSTS must explicitly list the backend hostname.")
    required_storage = ("S3_BUCKET", "S3_ENDPOINT_URL", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
    missing_storage = [name for name in required_storage if not os.getenv(name, "").strip()]
    if missing_storage:
        raise RuntimeError("Supabase Storage configuration is incomplete: " + ", ".join(missing_storage))

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Validate storage configuration and release shared connections on shutdown."""
    storage_backend()
    try:
        yield
    finally:
        close_database_pool()


app = FastAPI(
    title="LostLink", version="0.1.0", lifespan=lifespan,
    docs_url=None if AUTH_PROVIDER == "supabase" else "/docs",
    redoc_url=None if AUTH_PROVIDER == "supabase" else "/redoc",
    openapi_url=None if AUTH_PROVIDER == "supabase" else "/openapi.json",
)


def _apply_security_headers(response, private_api=False):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    response.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
    if private_api:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
    if HTTPS_ONLY:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
            "form-action 'self'; img-src 'self' data: blob:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "script-src 'self' https://cdn.jsdelivr.net; connect-src 'self' https://*.supabase.co https://*.storage.supabase.co; upgrade-insecure-requests",
        )
    return response


@app.middleware("http")
async def protect_unsafe_api_requests_and_add_headers(request: Request, call_next):
    """Reject cross-origin API mutations and add baseline browser security headers."""
    is_api = request.url.path.startswith("/api/")
    if is_api and request.method in {"POST", "PUT", "PATCH", "DELETE"} and not request.headers.get("authorization", "").lower().startswith("bearer "):
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            try:
                source_url = urlsplit(source)
                source_host = source_url.netloc.lower()
                request_host = request.headers.get("host", "").lower()
                source_scheme = source_url.scheme.lower()
                valid_scheme = source_scheme in {"http", "https"}
                if HTTPS_ONLY and source_scheme != "https":
                    valid_scheme = False
                source_origin = (source_url.scheme.lower() + "://" + source_host).rstrip("/")
                allowed_frontend_origin = source_origin in FRONTEND_ORIGINS
                same_origin = bool(source_host and source_host == request_host)
                if not valid_scheme or not (same_origin or allowed_frontend_origin):
                    return _apply_security_headers(JSONResponse(
                        status_code=403,
                        content={"detail": "Cross-origin state-changing requests are not allowed."},
                    ), private_api=True)
            except ValueError:
                return _apply_security_headers(JSONResponse(
                    status_code=403,
                    content={"detail": "Invalid request origin."},
                ), private_api=True)
        elif REQUIRE_REQUEST_ORIGIN:
            return _apply_security_headers(JSONResponse(
                status_code=403,
                content={"detail": "A same-origin request header is required."},
            ), private_api=True)
    return _apply_security_headers(await call_next(request), private_api=is_api)

app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="strict", https_only=HTTPS_ONLY, max_age=60 * 60 * 8)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
if FRONTEND_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=FRONTEND_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-LostLink-Tracking-Secret", "X-LostLink-Roll-Number"],
        max_age=600,
    )
@app.get("/health/live", include_in_schema=False)
def health_live():
    """Process liveness endpoint; does not depend on external services."""
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
    """Verify database, canonical schema and object storage without exposing secrets."""
    readiness_stage = "database_connection"
    try:
        with connect_db() as conn:
            conn.execute("SELECT 1 AS ready").fetchone()
            readiness_stage = "canonical_schema"
            conn.execute("SELECT id FROM reports LIMIT 0")
            conn.execute("SELECT id FROM claims LIMIT 0")
            version = conn.execute(
                "SELECT COALESCE(MAX(version),1) AS schema_version FROM schema_migrations"
            ).fetchone()["schema_version"]
        readiness_stage = "object_storage"
        storage_status = check_storage_ready()
    except Exception as exc:
        # Log only the failing stage and exception class. Never log connection
        # strings, credentials, request headers, or exception messages.
        import logging
        error_code = ""
        error_detail = ""
        http_status = ""
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            error = response.get("Error", {})
            metadata = response.get("ResponseMetadata", {})
            if isinstance(error, dict):
                error_code = str(error.get("Code", ""))[:80]
                # Provider error text distinguishes invalid credentials, signature
                # mismatch, missing bucket and denied bucket-level permissions.
                # Keep it short and strip control characters; never log headers or keys.
                error_detail = " ".join(str(error.get("Message", "")).split())[:180]
            if isinstance(metadata, dict):
                http_status = str(metadata.get("HTTPStatusCode", ""))[:8]
        logging.getLogger(__name__).error(
            "Readiness check failed at %s (%s, code=%s, http_status=%s, detail=%s)",
            readiness_stage,
            type(exc).__name__,
            error_code or "unavailable",
            http_status or "unavailable",
            error_detail or "unavailable",
        )
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "failed_check": readiness_stage,
                "fix_hint": {
                    "database_connection": "Check DATABASE_URL, database availability, network access and credentials.",
                    "canonical_schema": "Run the latest database migrations and verify the application database role can read reports and claims.",
                    "object_storage": "Check the private bucket name, endpoint, region, access key, secret key and bucket permissions.",
                }.get(readiness_stage, "Inspect the server logs for the failing readiness dependency."),
            },
        )
    return {
        "status": "ready",
        "database": "postgresql" if DATABASE_URL else "sqlite",
        "schema_version": int(version),
        "canonical_tables": "ready",
        "storage": storage_status,
    }


app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")
app.include_router(auth_router)
app.include_router(reports_router)
app.include_router(claims_router)
app.include_router(engagement_router)
app.include_router(public_workflow_router)
initialise_db()
ensure_public_schema()
