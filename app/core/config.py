"""Environment-backed configuration and shared privacy/category policy."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parents[2]  # app/core/config.py -> repository root
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
DB_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "lostlink.db"))).resolve()
# Optional managed PostgreSQL database. Leave unset for local SQLite development.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
AUTH_PROVIDER = os.getenv("AUTH_PROVIDER", "local").strip().lower()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
SUPABASE_REQUIRE_CONFIRMED_EMAIL = os.getenv("SUPABASE_REQUIRE_CONFIRMED_EMAIL", "true").lower() == "true"
OFFICE_USER_EMAILS = {email.strip().lower() for email in os.getenv("OFFICE_USER_EMAILS", "").split(",") if email.strip()}
ALLOWED_EMAIL_DOMAINS = {domain.strip().lower().lstrip("@") for domain in os.getenv("ALLOWED_EMAIL_DOMAINS", "").split(",") if domain.strip()}
FRONTEND_ORIGINS = [origin.strip().rstrip("/") for origin in os.getenv("FRONTEND_ORIGINS", "").split(",") if origin.strip()]
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(DATA_DIR / "uploads"))).resolve()
UPLOAD_STORAGE_BACKEND = os.getenv("UPLOAD_STORAGE_BACKEND", "local").strip().lower()
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
USE_IMAGE_ENRICHMENT = os.getenv("USE_IMAGE_ENRICHMENT", "false").lower() == "true"
IMAGE_CAPTION_MODEL = os.getenv("IMAGE_CAPTION_MODEL", "Salesforce/blip-image-captioning-base").strip()
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
MAX_OPEN_CLAIMS_PER_STUDENT = 5
try:
    MATCHING_CANDIDATE_LIMIT = int(os.getenv("MATCHING_CANDIDATE_LIMIT", "2000"))
except ValueError as exc:
    raise RuntimeError("MATCHING_CANDIDATE_LIMIT must be an integer between 100 and 10000.") from exc
if not 100 <= MATCHING_CANDIDATE_LIMIT <= 10000:
    raise RuntimeError("MATCHING_CANDIDATE_LIMIT must be between 100 and 10000.")
HTTPS_ONLY = os.getenv("SESSION_HTTPS_ONLY", "false").lower() == "true"
ALLOWED_HOSTS = [host.strip() for host in os.getenv("ALLOWED_HOSTS", "*").split(",") if host.strip()] or ["*"]
REQUIRE_REQUEST_ORIGIN = os.getenv("REQUIRE_REQUEST_ORIGIN", "false").lower() == "true"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EVIDENCE_TYPES = {
    "distinctive_features", "purchase_or_receipt", "packaging_or_accessory",
    "timeline_and_location", "device_or_account_context", "other"
}

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CATEGORY_LABELS = {
    "stationery": "Stationery & books",
    "clothing": "Clothing & everyday items",
    "bags_wallets": "Bags & wallets",
    "accessories": "Personal accessories",
    "electronics": "Electronics",
    "identity_documents": "Identity documents & cards",
    "keys_access": "Keys & access cards",
    "cash_jewellery": "Cash & jewellery",
    "sports_instruments": "Sports equipment & instruments",
    "other": "Other",
}
CATEGORY_DEFAULT_LEVEL = {
    "stationery": 1,
    "clothing": 1,
    "bags_wallets": 2,
    "accessories": 2,
    "electronics": 3,
    "identity_documents": 4,
    "keys_access": 4,
    "cash_jewellery": 3,
    "sports_instruments": 2,
    "other": 3,
}
SENSITIVE_CATEGORIES = {"identity_documents", "keys_access"}
ACTIVE_CLAIM_STATES = {"pending", "disputed", "needs_more_evidence", "approved_for_collection"}
