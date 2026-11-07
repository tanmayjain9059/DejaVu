"""Environment-backed configuration and shared privacy/category policy."""
from __future__ import annotations
import json
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def _directory_values(env_name: str, fallback: list[str], max_length: int) -> list[str]:
    """Load a bounded, de-duplicated JSON string array from the environment."""
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return list(fallback)
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{env_name} must be a JSON array of strings.") from exc
    if not isinstance(values, list) or not values or len(values) > 250:
        raise RuntimeError(f"{env_name} must contain between 1 and 250 values.")
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise RuntimeError(f"{env_name} values must be strings.")
        label = " ".join(value.split())
        key = label.casefold()
        if not label or len(label) > max_length:
            raise RuntimeError(f"{env_name} values must be 1-{max_length} characters.")
        if key in seen:
            raise RuntimeError(f"{env_name} values must be unique (case-insensitive).")
        cleaned.append(label)
        seen.add(key)
    return cleaned


# No campus-specific sample directory is assumed. Configure the verified
# institution directory at deployment; free-text area details remain available.
CAMPUS_BLOCKS = _directory_values("CAMPUS_BLOCKS", ["Other / not sure"], 80)
CAMPUS_FLOORS = _directory_values("CAMPUS_FLOORS", ["Other / not sure"], 40)

ROOT = Path(__file__).resolve().parents[2]  # app/core/config.py -> repository root
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
DB_PATH = Path(os.getenv("DATABASE_PATH", str(DATA_DIR / "lostlink.db"))).resolve()
# Optional managed PostgreSQL database. Leave unset for local SQLite development.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(DATA_DIR / "uploads"))).resolve()
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"
SESSION_SECRET = os.getenv("SESSION_SECRET", "").strip()
MAX_OPEN_CLAIMS_PER_STUDENT = 5
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
ACTIVE_CLAIM_STATES = {"pending", "disputed", "needs_more_evidence"}
