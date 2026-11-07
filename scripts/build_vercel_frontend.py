"""Prepare the static Vercel frontend with its separate FastAPI origin."""
from __future__ import annotations
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "app" / "static"
origin = os.environ.get("BACKEND_ORIGIN", "").strip().rstrip("/")
parsed = urlsplit(origin)
if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
    raise SystemExit("BACKEND_ORIGIN must be the HTTPS origin of the deployed LostLink API, without a path.")
if parsed.username or parsed.password:
    raise SystemExit("BACKEND_ORIGIN must not contain credentials.")
STATIC.mkdir(parents=True, exist_ok=True)
(STATIC / "deployment-config.js").write_text(
    "window.LOSTLINK_API_BASE_URL = " + json.dumps(origin) + ";\n",
    encoding="utf-8",
)
print("Prepared Vercel static frontend for " + origin)
