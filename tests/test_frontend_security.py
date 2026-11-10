from pathlib import Path
import os
import re
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def test_static_frontend_has_no_duplicate_ids_or_missing_literal_selectors():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), "index.html contains duplicate element IDs"
    known = set(ids)
    selectors = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', js))
    missing = sorted(selectors - known)
    assert not missing, f"app.js references missing static IDs: {missing}"


def test_frontend_does_not_load_third_party_scripts_or_inline_handlers():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    script_tags = re.findall(r"<script\b[^>]*>", html, flags=re.I)
    assert not any(re.search(r'\bsrc=["\']https?://', tag, flags=re.I) for tag in script_tags)
    assert not re.search(r'\son[a-z]+\s*=', html, flags=re.I)


def test_script_csp_is_same_origin_only():
    main = (ROOT / "app/main.py").read_text(encoding="utf-8")
    vercel = (ROOT / "vercel.json").read_text(encoding="utf-8")
    builder = (ROOT / "scripts/build_vercel_frontend.py").read_text(encoding="utf-8")
    for source in (main, vercel, builder):
        assert "script-src 'self'" in source
        assert "script-src 'self' 'unsafe-inline'" not in source
        assert "script-src 'self' https://" not in source


def test_public_workflow_has_no_duplicate_route_decorators_or_functions():
    source = (ROOT / "app/api/routes/public_workflow.py").read_text(encoding="utf-8")
    routes = re.findall(r'^@router\.(get|post|put|delete|patch)\("([^"]+)"', source, flags=re.M)
    route_keys = [method + " " + path for method, path in routes]
    functions = re.findall(r'^(?:async )?def ([A-Za-z_]\w*)\(', source, flags=re.M)
    assert len(route_keys) == len(set(route_keys)), "public_workflow.py contains duplicate method/path routes"
    assert len(functions) == len(set(functions)), "public_workflow.py contains duplicate helper definitions"


def test_cloudflare_worker_asset_build_emits_security_headers(tmp_path):
    # Both Cloudflare Workers (wrangler.jsonc) and Pages consume dist/_headers.
    config = (ROOT / "wrangler.jsonc").read_text(encoding="utf-8")
    assert '"directory": "./dist"' in config
    (tmp_path / "scripts").mkdir()
    (tmp_path / "app").mkdir()
    shutil.copy2(ROOT / "scripts/build_vercel_frontend.py",
                 tmp_path / "scripts/build_vercel_frontend.py")
    shutil.copytree(ROOT / "app/static", tmp_path / "app/static")
    env = dict(os.environ, BACKEND_ORIGIN="https://lostlink-q8ft.onrender.com")
    subprocess.run([sys.executable, str(tmp_path / "scripts/build_vercel_frontend.py")],
                   cwd=tmp_path, env=env, check=True, capture_output=True, text=True)
    headers = (tmp_path / "dist/_headers").read_text(encoding="utf-8")
    for required in (
        "Strict-Transport-Security: max-age=31536000",
        "X-Content-Type-Options: nosniff",
        "X-Frame-Options: DENY",
        "Referrer-Policy: strict-origin-when-cross-origin",
        "Content-Security-Policy: default-src 'self'",
        "script-src 'self'",
        "connect-src 'self' https://lostlink-q8ft.onrender.com",
    ):
        assert required in headers
    assert "script-src 'self' 'unsafe-inline'" not in headers
    assert (tmp_path / "dist/index.html").exists()


def test_retired_office_ai_status_route_is_absent():
    from app.main import app
    assert not any(
        getattr(route, "path", None) == "/api/office/ai-status"
        for route in app.routes
    )
