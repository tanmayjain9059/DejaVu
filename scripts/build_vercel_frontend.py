"""Prepare the static Vercel frontend with its separate FastAPI origin."""
from __future__ import annotations
import json
import os
import shutil
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
DIST = ROOT / "dist"
origin = os.environ.get("BACKEND_ORIGIN", "https://lostlink-q8ft.onrender.com").strip().rstrip("/")
if origin:
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise SystemExit("BACKEND_ORIGIN must be the HTTPS origin of the deployed LostLink API, without a path.")
    if parsed.username or parsed.password:
        raise SystemExit("BACKEND_ORIGIN must not contain credentials.")
else:
    raise SystemExit("BACKEND_ORIGIN resolved to an empty value; configure the deployed LostLink API origin.")
STATIC.mkdir(parents=True, exist_ok=True)
(STATIC / "deployment-config.js").write_text(
    "window.LOSTLINK_API_BASE_URL = " + json.dumps(origin) + ";\n" +
    "window.LOSTLINK_DEPLOYMENT_CONFIGURED = " + ("true" if origin else "false") + ";\n",
    encoding="utf-8",
)
if DIST.exists():
    shutil.rmtree(DIST)
shutil.copytree(STATIC, DIST / "static")
shutil.copy2(STATIC / "index.html", DIST / "index.html")
shutil.copy2(STATIC / "deployment-config.js", DIST / "deployment-config.js")

(DIST / "_headers").write_text(
    """/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
  Cross-Origin-Resource-Policy: same-origin
  Content-Security-Policy: default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; img-src 'self' data: blob: """ + origin + """; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; script-src 'self' https://cdn.jsdelivr.net; connect-src 'self' """ + origin + """ https://*.supabase.co https://*.storage.supabase.co; upgrade-insecure-requests
""",
    encoding="utf-8",
)
print("Prepared Vercel static frontend for " + origin)
