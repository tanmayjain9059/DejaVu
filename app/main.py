"""FastAPI application composition root for LostLink."""
from __future__ import annotations
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
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
from app.api.routes.auth import router as auth_router
from app.api.routes.reports import router as reports_router
from app.api.routes.claims import router as claims_router
from app.api.routes.engagement import router as engagement_router

if not SESSION_SECRET or SESSION_SECRET in {
    "replace-with-a-long-random-secret-before-running",
    "local-development-only-change-this",
}:
    raise RuntimeError("SESSION_SECRET is unset or a placeholder. Set a unique random secret in .env before starting LostLink.")

@asynccontextmanager
async def lifespan(application: FastAPI):
    """Release shared PostgreSQL connections gracefully when the app shuts down."""
    try:
        yield
    finally:
        close_database_pool()


app = FastAPI(title="LostLink", version="0.1.0", lifespan=lifespan)


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
            "script-src 'self' 'unsafe-inline'; connect-src 'self'; upgrade-insecure-requests",
        )
    return response


@app.middleware("http")
async def protect_unsafe_api_requests_and_add_headers(request: Request, call_next):
    """Reject cross-origin API mutations and add baseline browser security headers."""
    is_api = request.url.path.startswith("/api/")
    if is_api and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        source = request.headers.get("origin") or request.headers.get("referer")
        if source:
            try:
                source_url = urlsplit(source)
                source_host = source_url.netloc.lower()
                request_host = request.headers.get("host", "").lower()
                valid_scheme = source_url.scheme.lower() in {"http", "https"}
                if not valid_scheme or not source_host or source_host != request_host:
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
@app.get("/health/live", include_in_schema=False)
def health_live():
    """Process liveness endpoint; does not depend on external services."""
    return {"status": "ok"}


@app.get("/health/ready", include_in_schema=False)
def health_ready():
    """Readiness endpoint that verifies a usable database connection."""
    try:
        with connect_db() as conn:
            conn.execute("SELECT 1 AS ready").fetchone()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})
    return {"status": "ready"}


app.mount("/static", StaticFiles(directory=str(ROOT / "app" / "static")), name="static")
app.include_router(auth_router)
app.include_router(reports_router)
app.include_router(claims_router)
app.include_router(engagement_router)
initialise_db()
