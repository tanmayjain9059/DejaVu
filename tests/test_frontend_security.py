from pathlib import Path
import re


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
    routes = re.findall(r'^@router\.(?:get|post|put|delete|patch)\("([^"]+)"', source, flags=re.M)
    functions = re.findall(r'^(?:async )?def ([A-Za-z_]\w*)\(', source, flags=re.M)
    assert len(routes) == len(set(routes)), "public_workflow.py contains duplicate route paths"
    assert len(functions) == len(set(functions)), "public_workflow.py contains duplicate helper definitions"
