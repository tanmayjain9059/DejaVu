"""No-login student API backed by the canonical LostLink reports and claims tables.

A college roll number is attribution only. It never authenticates a request.
Every report and claim receives an independent, high-entropy tracking secret;
only its SHA-256 digest is persisted. Public students are represented internally
by non-login attribution principals so existing audit, matching, notification,
and reward services can be reused without exposing a student sign-in surface.
"""
from __future__ import annotations

import hashlib
import ipaddress
import hmac
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from app.schemas import ImageAiConsentBody

from app.core.config import (
    ALLOWED_EVIDENCE_TYPES,
    CATEGORY_LABELS,
    DATABASE_URL,
    MATCHING_CANDIDATE_LIMIT,
    MAX_UPLOAD_BYTES,
    SESSION_SECRET,
    MAX_OPEN_CLAIMS_PER_STUDENT,
    UPLOAD_DIR,
)
from app.core.database import audit, connect_db, lock_advisory_key, lock_row, now_iso, table_columns
from app.core.security import hash_password
from app.core.images import canonicalise_image
from app.services.notifications import notify_matches_for_lost_report, notify_role, notify_user
from app.services.reports import read_report, serialise_report
from app.services.object_storage import delete_upload, read_upload, save_upload

router = APIRouter(prefix="/api/public", tags=["public-student-workflow"])
ROLL_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{4,19}$")
ACTIVE_CLAIMS = ("pending", "disputed", "needs_more_evidence", "approved_for_collection")


def _roll(value: str) -> str:
    value = value.strip().upper()
    if not ROLL_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail="Enter a valid college roll number.")
    return value


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_token() -> str:
    return secrets.token_urlsafe(32)


def _verify_token(stored_hash: str | None, token: str | None) -> bool:
    return bool(stored_hash and token) and secrets.compare_digest(stored_hash, _hash(token))


def _reference(prefix: str) -> str:
    return prefix + "-" + secrets.token_hex(16).upper()


def _public_actor_for_roll(conn, roll_number: str) -> int:
    """Get a non-login internal principal; never use the roll number as a credential."""
    existing = conn.execute(
        "SELECT user_id FROM public_roll_identities WHERE roll_number=?",
        (roll_number,),
    ).fetchone()
    if existing:
        return int(existing["user_id"])
    email = "public-" + uuid.uuid4().hex + "@no-login.lostlink.invalid"
    random_password = secrets.token_urlsafe(48)
    conn.execute(
        """INSERT INTO users(email, display_name, role, password_hash, created_at)
           VALUES (?, ?, 'student', ?, ?)""",
        (email, "Public student", hash_password(random_password), now_iso()),
    )
    actor = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if not actor:
        raise RuntimeError("Could not provision public attribution identity.")
    actor_id = int(actor["id"])
    conn.execute(
        "INSERT INTO public_roll_identities(roll_number,user_id,created_at) VALUES (?,?,?)",
        (roll_number, actor_id, now_iso()),
    )
    return actor_id


def _trusted_client_ip(request: Request) -> str:
    """Use Cloudflare's edge-overwritten client IP; never trust client-supplied X-Forwarded-For."""
    candidate = (request.headers.get("cf-connecting-ip") or "").strip()
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return request.client.host if request.client else "unknown"


def _enforce_rate_limit(conn, request: Request, action: str, maximum: int, window_minutes: int = 60) -> None:
    """Rate-limit anonymous writes while storing only a one-way IP digest."""
    address = _trusted_client_ip(request)
    from app.core.database import lock_advisory_key as _lock_advisory_key
    _lock_advisory_key(conn, "public-rate:" + action, address)
    hash_key = (SESSION_SECRET or "lostlink-local-rate-limit-secret").encode("utf-8")
    ip_hash = hmac.new(hash_key, address.encode("utf-8"), hashlib.sha256).hexdigest()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat(timespec="seconds")
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM public_rate_limits WHERE ip_hash=? AND action=? AND created_at>=?",
        (ip_hash, action, cutoff),
    ).fetchone()["n"]
    if int(count) >= maximum:
        raise HTTPException(status_code=429, detail="Too many submissions. Please try again later.")
    conn.execute(
        "INSERT INTO public_rate_limits(id,ip_hash,action,created_at) VALUES (?,?,?,?)",
        (uuid.uuid4().hex, ip_hash, action, now_iso()),
    )


def _public_report(row) -> dict[str, Any]:
    item = serialise_report(row, internal=False)
    # Public image access is deliberately withheld until the private-storage,
    # per-case signed-access flow is enabled for anonymous tracking tokens.
    item["image_url"] = None
    item.pop("image_ai_consent", None)
    item.pop("location_room", None)
    # Found-item free text may contain a finder's or owner's personal data.
    # Public browse exposes controlled descriptors only; full notes remain
    # available to authorised office staff during ownership verification.
    if item.get("report_type") == "found":
        item["title"] = "Found item"
        item["description"] = "A found item is held by the campus office. Share private ownership evidence when claiming."
        item["brand"] = None
        item["visible_features"] = None
    if item.get("category") in {"identity_documents", "keys_access"}:
        # Do not publicly label identity documents or access credentials.
        item["category"] = "other"
        item["category_label"] = "Personal item"
        if item.get("report_type") == "found":
            item["title"] = "Personal item held by the campus office"
    # Public Lost listings must not reveal a precise loss location or time.
    if item.get("report_type") == "lost":
        item["location"] = "CVR campus"
        item["location_block"] = None
        item["location_floor"] = None
        item["location_area"] = None
        item["occurred_at"] = None
    item["reference"] = item["public_ref"]
    return item


def _case_points(conn, user_id: int, entity_id: str) -> int:
    row = conn.execute("SELECT COALESCE(SUM(points),0) AS total FROM reward_ledger WHERE user_id=? AND report_id=?", (user_id,entity_id)).fetchone()
    return int(row["total"] or 0)


def _tracking_events(conn, user_id: int, entity_type: str, entity_id: str) -> list[dict[str, str]]:
    rows = conn.execute(
        """SELECT title,message,created_at FROM notifications
           WHERE user_id=? AND entity_type=? AND entity_id=?
           ORDER BY created_at DESC LIMIT 25""",
        (user_id, entity_type, entity_id),
    ).fetchall()
    return [dict(row) for row in rows]


async def _rank_public_matches_async(lost_report_id: str) -> list[dict[str, Any]]:
    """Use the same two-tier retrieval and AI ranking path as authenticated reports."""
    from app.matching import matching_engine
    
    with connect_db() as conn:
        lost_row = conn.execute("SELECT * FROM reports WHERE id=?", (lost_report_id,)).fetchone()
        if not lost_row or lost_row["report_type"] != "lost" or lost_row["status"] != "open":
            return []
        candidate_limit = MATCHING_CANDIDATE_LIMIT
        category_limit = max(1, int(candidate_limit * 0.75))
        fallback_limit = candidate_limit - category_limit
        candidates_by_id = {}
        if lost_row["category"]:
            category_rows = conn.execute(
                """SELECT * FROM reports
                   WHERE report_type='found' AND status='available' AND category=?
                   ORDER BY created_at DESC,id DESC LIMIT ?""",
                (lost_row["category"],category_limit),
            ).fetchall()
            candidates_by_id.update({row["id"]: row for row in category_rows})
            if fallback_limit:
                fallback_match = ["category<>?", "category IS NULL"]
                fallback_params: list[Any] = [lost_row["category"]]
                if lost_row["location_block"]:
                    fallback_match.append("LOWER(COALESCE(location_block,''))=LOWER(?)")
                    fallback_params.append(lost_row["location_block"])
                if lost_row["location_area"]:
                    fallback_match.append("LOWER(COALESCE(location_area,''))=LOWER(?)")
                    fallback_params.append(lost_row["location_area"])
                fallback_sql = (
                    "SELECT * FROM reports WHERE report_type='found' AND status='available' "
                    "AND (" + " OR ".join(fallback_match) + ") "
                    "ORDER BY created_at DESC,id DESC LIMIT ?"
                )
                fallback_params.append(fallback_limit)
                fallback_rows = conn.execute(fallback_sql,fallback_params).fetchall()
                candidates_by_id.update({row["id"]: row for row in fallback_rows})
        else:
            recent_rows = conn.execute(
                """SELECT * FROM reports WHERE report_type='found' AND status='available'
                   ORDER BY created_at DESC,id DESC LIMIT ?""",
                (candidate_limit,),
            ).fetchall()
            candidates_by_id.update({row["id"]: row for row in recent_rows})
        candidates = list(candidates_by_id.values())

    lost = dict(lost_row)
    if lost.get("image_path"):
        lost["image_key"] = lost["image_path"]
        lost["image_loader"] = read_upload
        lost["image_path"] = str(UPLOAD_DIR / lost["image_path"])
    candidate_data = []
    for row in candidates:
        candidate = dict(row)
        if candidate.get("image_path"):
            candidate["image_key"] = candidate["image_path"]
            candidate["image_loader"] = read_upload
            candidate["image_path"] = str(UPLOAD_DIR / candidate["image_path"])
        candidate_data.append(candidate)

    ranked = await run_in_threadpool(matching_engine.rank,lost,candidate_data,limit=5)
    ranked_ids = [match["report"]["id"] for match in ranked]
    fresh_by_id = {}
    if ranked_ids:
        placeholders = ",".join("?" for _ in ranked_ids)
        with connect_db() as conn:
            fresh_rows = conn.execute(
                f"""SELECT * FROM reports WHERE id IN ({placeholders})
                    AND report_type='found' AND status='available'""",
                ranked_ids,
            ).fetchall()
            fresh_by_id = {row["id"]: row for row in fresh_rows}
    results = []
    for match in ranked:
        fresh = fresh_by_id.get(match["report"]["id"])
        if fresh is None:
            continue
        results.append({
            "report": _public_report(fresh),
            "strength": match["strength"],
            "reasons": match["reasons"],
        })
    return results


class PublicCategorySuggestionBody(BaseModel):
    title: str = Field(default="", max_length=100)
    description: str = Field(default="", max_length=1200)
    brand: str | None = Field(default=None, max_length=80)
    primary_color: str | None = Field(default=None, max_length=60)
    visible_features: str | None = Field(default=None, max_length=400)


class PublicReportBody(BaseModel):
    report_type: Literal["lost", "found"]
    image_ai_consent: bool = False
    roll_number: str = Field(min_length=5, max_length=20)
    contact_phone: str | None = Field(default=None, max_length=20)
    contact_email: str | None = Field(default=None, max_length=254)
    title: str = Field(min_length=4, max_length=100)
    description: str = Field(min_length=10, max_length=1200)
    category: str = Field(min_length=2, max_length=60)
    brand: str | None = Field(default=None, max_length=80)
    primary_color: str | None = Field(default=None, max_length=60)
    visible_features: str | None = Field(default=None, max_length=400)
    occurred_at: str | None = None
    location_block: str | None = Field(default=None, max_length=80)
    location_floor: str | None = Field(default=None, max_length=40)
    location_room: str | None = Field(default=None, max_length=80)
    location_area: str | None = Field(default=None, max_length=120)
    private_detail: str | None = Field(default=None, max_length=1200)
    item_condition: Literal["good", "damaged", "partially_damaged", "unknown"] | None = None
    handover_at: str | None = None
    handover_recipient: str | None = Field(default=None, max_length=120)
    handover_note: str | None = Field(default=None, max_length=800)


class PublicPrivacyRequestBody(BaseModel):
    reference: str = Field(min_length=4, max_length=32)
    roll_number: str = Field(min_length=5, max_length=20)
    tracking_secret: str = Field(min_length=24, max_length=128)
    request_type: Literal["access", "correction", "erasure"]
    details: str = Field(default="", max_length=2000)


class PublicClaimBody(BaseModel):
    roll_number: str = Field(min_length=5, max_length=20)
    contact_phone: str | None = Field(default=None, max_length=20)
    evidence: str = Field(min_length=20, max_length=1800)
    evidence_types: list[str] = Field(min_length=1, max_length=6)
    lost_report_reference: str | None = Field(default=None, max_length=24)


class PublicEvidenceBody(BaseModel):
    evidence: str = Field(min_length=20, max_length=1800)


class PublicCloseBody(BaseModel):
    reason: Literal["recovered_elsewhere", "no_longer_searching", "duplicate", "found_report_withdrawn"]
    note: str | None = Field(default=None, max_length=400)


def ensure_public_schema() -> None:
    """Idempotently migrate records from the retired parallel public tables."""
    with connect_db() as conn:
        if DATABASE_URL:
            # Serialise one-time schema setup across simultaneously starting workers.
            conn.execute("SELECT pg_advisory_xact_lock(730022)")
        # Prune expired anonymous rate-limit digests at startup, not on every
        # public request. The table contains no raw IP addresses.
        retention_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
        conn.execute("DELETE FROM public_rate_limits WHERE created_at < ?", (retention_cutoff,))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS public_schema_migrations (
                version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
            )"""
        )
        if DATABASE_URL:
            # Migration bookkeeping is server-only; browser roles have no access.
            conn.execute("ALTER TABLE public_schema_migrations ENABLE ROW LEVEL SECURITY")
            conn.execute("REVOKE ALL ON TABLE public_schema_migrations FROM anon, authenticated")
        case_columns = table_columns(conn, "public_cases")
        claim_columns = table_columns(conn, "public_claims")
        if case_columns and {"id", "public_ref", "roll_number", "tracking_hash"}.issubset(case_columns):
            legacy_cases = conn.execute("SELECT * FROM public_cases ORDER BY created_at").fetchall()
            for old in legacy_cases:
                if conn.execute("SELECT 1 FROM reports WHERE id=?", (old["id"],)).fetchone():
                    continue
                actor_id = _public_actor_for_roll(conn, _roll(old["roll_number"]))
                conn.execute(
                    """INSERT INTO reports
                       (id,public_ref,report_type,title,description,brand,primary_color,visible_features,
                        category,occurred_at,location_block,location_floor,location_room,location_area,
                        status,created_by,tag_id,storage_location,private_detail,created_at,updated_at,
                        roll_number,tracking_hash,submission_channel)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'public')""",
                    (old["id"],old["public_ref"],old["report_type"],old["title"],old["description"],
                     old["brand"],old["primary_color"],old["visible_features"],old["category"],
                     old["occurred_at"],old["location_block"],old["location_floor"],old["location_room"],
                     old["location_area"],old["status"],actor_id,old["tag_id"],old["storage_location"],
                     old["private_detail"],old["created_at"],old["updated_at"],old["roll_number"],old["tracking_hash"]),
                )
        if claim_columns and {"id", "public_ref", "case_id", "roll_number", "tracking_hash"}.issubset(claim_columns):
            legacy_claims = conn.execute("SELECT * FROM public_claims ORDER BY created_at").fetchall()
            for old in legacy_claims:
                if conn.execute("SELECT 1 FROM claims WHERE id=?", (old["id"],)).fetchone():
                    continue
                actor_id = _public_actor_for_roll(conn, _roll(old["roll_number"]))
                conn.execute(
                    """INSERT INTO claims
                       (id,public_ref,report_id,claimant_id,evidence,evidence_types,status,reviewer_id,
                        reviewer_note,created_at,updated_at,claimant_roll_number,tracking_hash,submission_channel)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'public')""",
                    (old["id"],old["public_ref"],old["case_id"],actor_id,old["evidence"],old["evidence_types"],
                     old["status"],old["reviewer_id"],old["reviewer_note"],old["created_at"],old["updated_at"],
                     old["roll_number"],old["tracking_hash"]),
                )
        conn.execute(
            """INSERT INTO public_schema_migrations(version,name,applied_at)
               VALUES (2,'migrate_parallel_public_records_to_canonical_workflow',?)
               ON CONFLICT(version) DO NOTHING""",
            (now_iso(),),
        )


@router.post("/category-suggestion")
async def suggest_public_category(body: PublicCategorySuggestionBody, request: Request):
    """Rate-limited anonymous category helper; suggestions never modify a report."""
    from starlette.concurrency import run_in_threadpool
    from app.services.category_classification import suggest_category

    with connect_db() as conn:
        _enforce_rate_limit(conn, request, "ai_category", 30, window_minutes=60)
    payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    result = await run_in_threadpool(suggest_category, payload)
    return {"suggestion": result}


@router.post("/reports", status_code=201)
async def submit_public_report(body: PublicReportBody, request: Request):
    roll = _roll(body.roll_number)
    contact_phone = (body.contact_phone or "").strip() or None
    contact_email = (body.contact_email or "").strip().lower() or None
    if contact_phone:
        phone_digits = re.sub(r"\D", "", contact_phone)
        if not 7 <= len(phone_digits) <= 15:
            raise HTTPException(status_code=422, detail="Enter a valid phone number with 7 to 15 digits.")
    if contact_email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", contact_email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if body.category not in CATEGORY_LABELS:
        raise HTTPException(status_code=422, detail="Choose a valid item category.")
    if not (body.location_block or body.location_area):
        raise HTTPException(status_code=422, detail="Choose a campus building or area.")
    if body.location_block == "Other / Not listed" and not body.location_area:
        raise HTTPException(status_code=422, detail="Add a location detail when choosing Other / Not listed.")
    if body.occurred_at:
        try:
            datetime.fromisoformat(body.occurred_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Use a valid ISO date and time.")
    if body.handover_at:
        if body.report_type != "found":
            raise HTTPException(status_code=422, detail="Handover details are only valid for Found reports.")
        try:
            datetime.fromisoformat(body.handover_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Use a valid handover date and time.")
    if body.report_type == "lost" and any((body.item_condition, body.handover_at, body.handover_recipient, body.handover_note)):
        raise HTTPException(status_code=422, detail="Found-item condition and handover details cannot be added to a Lost report.")
    token = _issue_token()
    report_id = uuid.uuid4().hex
    public_ref = _reference("LL")
    status = "open" if body.report_type == "lost" else "awaiting_intake"
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _enforce_rate_limit(conn, request, "report", 10)
        from app.core.database import lock_advisory_key as _lock_advisory_key
        _lock_advisory_key(conn, "public-roll", roll)
        actor_id = _public_actor_for_roll(conn, roll)
        timestamp = now_iso()
        conn.execute(
            """INSERT INTO reports
               (id,public_ref,report_type,title,description,brand,primary_color,visible_features,
                category,occurred_at,location_block,location_floor,location_room,location_area,
                image_ai_consent,private_detail,item_condition,handover_at,handover_recipient,handover_note,
                contact_phone,contact_email,status,created_by,created_at,updated_at,roll_number,tracking_hash,submission_channel)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'public')""",
            (report_id,public_ref,body.report_type,body.title.strip(),body.description.strip(),
             body.brand,body.primary_color,body.visible_features,body.category,body.occurred_at,
             body.location_block,body.location_floor,body.location_room,body.location_area,
             int(body.image_ai_consent), body.private_detail if body.report_type == "lost" else None,
             body.item_condition,body.handover_at,body.handover_recipient,body.handover_note,
             contact_phone,contact_email,status,actor_id,timestamp,timestamp,roll,_hash(token)),
        )
        audit(conn, actor_id, "public_report_submitted", "report", report_id,
              {"report_type": body.report_type, "channel": "public"})
        if body.report_type == "found":
            notify_role(conn,"office","public-intake:"+report_id,"Found item awaiting physical intake",
                        "A public Found report is waiting for physical receipt and tagging.",
                        "report",report_id)
            notify_user(conn,actor_id,"public-report:"+report_id,"Found report received",
                        "Your Found report is waiting for the campus office to receive and tag the physical item.",
                        "report",report_id)
        else:
            row = read_report(conn,report_id)
            notify_matches_for_lost_report(conn,row)
            notify_user(conn,actor_id,"public-report:"+report_id,"Lost report received",
                        "Your Lost report is open. Track it with the private reference and one-time secret.",
                        "report",report_id)
    matches = []
    if body.report_type == "lost":
        try:
            matches = await _rank_public_matches_async(report_id)
        except Exception:
            logging.exception("Public lost-report matching failed for %s", public_ref)
    return {
        "case": {"id": report_id, "reference": public_ref, "status": status},
        "tracking_secret": token,
        "message": "Save this tracking secret now. It is shown once; your roll number alone never grants access.",
        "matches": matches,
    }



def _verify_public_image_access(reference: str, roll: str, tracking_secret: str, request: Request) -> dict[str, Any]:
    """Authenticate the case and consume its upload quota before image processing."""
    with connect_db() as conn:
        lock_row(conn, "reports", "public_ref", reference)
        row = conn.execute("SELECT * FROM reports WHERE public_ref=?", (reference,)).fetchone()
        if not row or row["submission_channel"] != "public" or row["roll_number"] != roll or not _verify_token(row["tracking_hash"], tracking_secret):
            raise HTTPException(status_code=404, detail="Tracking access not found.")
        if row["status"] not in {"open", "awaiting_intake"}:
            raise HTTPException(status_code=409, detail="This report is no longer accepting photo updates.")
        _enforce_rate_limit(conn, request, "image", 5)
        return {"id": row["id"], "created_by": int(row["created_by"])}


def _persist_public_report_image(reference: str, case_id: str, actor_id: int, raw: bytes) -> None:
    """Persist image bytes outside the DB transaction; serialize only the final fingerprint check."""
    normalized, image_sha256, image_phash = canonicalise_image(raw)
    new_key = uuid.uuid4().hex + ".jpg"
    old_key = None
    saved = False
    try:
        # Object storage I/O must never happen while holding a database write lock.
        save_upload(new_key, normalized)
        saved = True
        with connect_db() as conn:
            # Recheck under the write transaction so simultaneous uploads of the
            # same image cannot both pass the duplicate test.
            conn.execute("BEGIN IMMEDIATE")
            lock_row(conn, "reports", "id", case_id)
            row = conn.execute(
                "SELECT image_path,status FROM reports WHERE id=? AND public_ref=? AND submission_channel='public'",
                (case_id, reference),
            ).fetchone()
            if not row or row["status"] not in {"open", "awaiting_intake"}:
                raise HTTPException(status_code=409, detail="This report is no longer accepting photo updates.")
            old_key = row["image_path"]
            conn.execute(
                "UPDATE reports SET image_path=?, image_sha256=?, image_phash=?, updated_at=? WHERE id=?",
                (new_key, image_sha256, image_phash, now_iso(), case_id),
            )
            audit(conn, actor_id, "public_report_image_added", "report", case_id)
    except Exception:
        if saved:
            try:
                delete_upload(new_key)
            except Exception:
                logging.exception("Could not clean up failed public report image %s", new_key)
        raise
    if old_key and old_key != new_key:
        try:
            delete_upload(old_key)
        except Exception:
            logging.exception("Could not remove replaced public report image %s", old_key)



@router.post("/reports/{reference}/image")
async def upload_public_report_image(
    reference: str,
    request: Request,
    file: UploadFile = File(...),
    roll_number: str = Header(..., alias="X-LostLink-Roll-Number"),
    tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret"),
):
    """Attach an optional private photo to a public report using its one-time credentials."""
    roll = _roll(roll_number)
    access = await run_in_threadpool(_verify_public_image_access, reference, roll, tracking_secret, request)
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Images must be 5 MB or smaller.")
    await run_in_threadpool(_persist_public_report_image, reference, access["id"], access["created_by"], raw)
    return {"reference": reference, "image_uploaded": True, "message": "Your photo was saved privately for office review and matching."}


@router.get("/search")
def search_public_reports(category: str | None = Query(default=None, max_length=60), q: str | None = Query(default=None, max_length=100), report_type: Literal["all", "lost", "found"] = "all", limit: int = Query(default=50, ge=1, le=100)):
    """Public discovery across open Lost reports and office-received Found inventory."""
    if category and category not in CATEGORY_LABELS:
        raise HTTPException(status_code=422, detail="Choose a valid report category.")
    clauses = []
    params: list[Any] = []
    if report_type in {"all", "lost"}:
        clauses.append("(report_type='lost' AND status='open')")
    if report_type in {"all", "found"}:
        clauses.append("(report_type='found' AND status='available')")
    where = "(" + " OR ".join(clauses) + ")"
    if category and category in CATEGORY_LABELS:
        where += " AND category=?"
        params.append(category)
    if q and q.strip():
        term = "%" + q.strip().lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        where += " AND (LOWER(category) LIKE ? ESCAPE '!' OR LOWER(COALESCE(primary_color,'')) LIKE ? ESCAPE '!' OR LOWER(COALESCE(public_ref,'')) LIKE ? ESCAPE '!')"
        params.extend([term,term,term])
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM reports WHERE " + where + " ORDER BY created_at DESC,id DESC LIMIT ?", (*params,limit)).fetchall()
    return {"reports": [_public_report(row) for row in rows]}


@router.get("/found/{report_id}")
def get_public_found_item(report_id: str):
    """Fetch one claimable Found item by its canonical report ID."""
    with connect_db() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE id=? AND report_type='found' AND status='available'",
            (report_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="This Found item is no longer available for claims. Refresh Browse.")
    return {"report": _public_report(row)}


@router.get("/found")
def browse_public_found(category: str | None = Query(default=None, max_length=60), q: str | None = Query(default=None, max_length=100), limit: int = Query(default=50, ge=1, le=100)):
    if category and category not in CATEGORY_LABELS:
        raise HTTPException(status_code=422, detail="Choose a valid report category.")
    clauses = ["report_type='found'", "status='available'"]
    params: list[Any] = []
    if category and category in CATEGORY_LABELS:
        clauses.append("category=?")
        params.append(category)
    if q and q.strip():
        term = "%" + q.strip().lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        clauses.append(
            "(LOWER(category) LIKE ? ESCAPE '!' OR LOWER(COALESCE(primary_color,'')) LIKE ? ESCAPE '!' OR LOWER(COALESCE(public_ref,'')) LIKE ? ESCAPE '!')"
        )
        params.extend([term,term,term])
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT * FROM reports WHERE " + " AND ".join(clauses) +
            " ORDER BY created_at DESC,id DESC LIMIT ?",
            (*params,limit),
        ).fetchall()
    return {"reports": [_public_report(row) for row in rows]}


@router.get("/reports/{reference}/matches")
async def public_report_matches(
    reference: str,
    request: Request,
    roll_number: str = Header(..., alias="X-LostLink-Roll-Number"),
    tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret"),
):
    roll = _roll(roll_number)
    with connect_db() as conn:
        _enforce_rate_limit(conn, request, "matches", 20, window_minutes=60)
        row = conn.execute("SELECT * FROM reports WHERE public_ref=?", (reference,)).fetchone()
        if not row or row["report_type"] != "lost" or row["roll_number"] != roll or not _verify_token(row["tracking_hash"],tracking_secret):
            raise HTTPException(status_code=404,detail="Tracking access not found.")
        report_id = row["id"]
    return {
        "matches": await _rank_public_matches_async(report_id),
        "note": "Suggestions support discovery only; they do not establish ownership.",
    }


@router.get("/track/{reference}")
def track_one_case(
    reference: str,
    roll_number: str = Header(..., alias="X-LostLink-Roll-Number"),
    tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret"),
):
    roll = _roll(roll_number)
    with connect_db() as conn:
        report = conn.execute("SELECT * FROM reports WHERE public_ref=?", (reference,)).fetchone()
        if report and report["roll_number"] == roll and report["submission_channel"] == "public" and _verify_token(report["tracking_hash"],tracking_secret):
            case_data = _public_report(report)
            case_data["image_ai_consent"] = bool(report["image_ai_consent"])
            return {
                "case": case_data,
                "events": _tracking_events(conn,int(report["created_by"]),"report",report["id"]),
                "case_points": _case_points(conn,int(report["created_by"]),report["id"]),
            }
        lock_row(conn, "claims", "public_ref", reference)
        claim = conn.execute("SELECT * FROM claims WHERE public_ref=?", (reference,)).fetchone()
        if claim and claim["claimant_roll_number"] == roll and claim["submission_channel"] == "public" and _verify_token(claim["tracking_hash"],tracking_secret):
            parent = conn.execute("SELECT * FROM reports WHERE id=?", (claim["report_id"],)).fetchone()
            return {
                "claim": {
                    "reference": claim["public_ref"],
                    "status": claim["status"],
                    "evidence": claim["evidence"],
                    "created_at": claim["created_at"],
                },
                "item": _public_report(parent),
                "events": _tracking_events(conn,int(claim["claimant_id"]),"claim",claim["id"]),
                "case_points": _case_points(conn,int(claim["claimant_id"]),claim["report_id"]),
            }
    raise HTTPException(status_code=404,detail="Tracking access not found.")


@router.post("/cases/{reference}/close")
def close_public_case(
    reference: str,
    body: PublicCloseBody,
    roll_number: str = Header(..., alias="X-LostLink-Roll-Number"),
    tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret"),
):
    roll = _roll(roll_number)
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row(conn, "reports", "public_ref", reference)
        row = conn.execute("SELECT * FROM reports WHERE public_ref=?", (reference,)).fetchone()
        if not row or row["submission_channel"] != "public" or row["roll_number"] != roll or not _verify_token(row["tracking_hash"],tracking_secret):
            raise HTTPException(status_code=404,detail="Tracking access not found.")
        if row["report_type"] == "lost" and row["status"] == "open":
            if body.reason == "found_report_withdrawn":
                raise HTTPException(status_code=422,detail="Choose a Lost-report closure reason.")
            new_status = "closed"
        elif row["report_type"] == "found" and row["status"] == "awaiting_intake":
            if body.reason != "found_report_withdrawn":
                raise HTTPException(status_code=422,detail="Choose the Found-report withdrawal reason.")
            new_status = "cancelled"
        else:
            raise HTTPException(status_code=409,detail="This report can no longer be withdrawn.")
        conn.execute(
            "UPDATE reports SET status=?,closure_reason=?,closure_note=?,updated_at=? WHERE id=?",
            (new_status,body.reason,body.note,now_iso(),row["id"]),
        )
        audit(conn,int(row["created_by"]),"public_report_closed","report",row["id"],{"reason":body.reason})
        notify_user(conn,int(row["created_by"]),"public-report-closed:"+row["id"],"Report closed",
                    "Your LostLink report status was updated to "+new_status+".","report",row["id"])
        if row["report_type"] == "found":
            notify_role(conn,"office","public-withdrawal:"+row["id"],"Found report withdrawn",
                        "A public Found report was withdrawn before physical intake.","report",row["id"])
    return {"reference":reference,"status":new_status,"message":"Report status updated."}


@router.post("/found/{report_id}/claims", status_code=201)
def submit_public_claim(report_id: str, body: PublicClaimBody, request: Request):
    roll = _roll(body.roll_number)
    contact_phone = (body.contact_phone or "").strip() or None
    if contact_phone:
        phone_digits = re.sub(r"\D", "", contact_phone)
        if not 7 <= len(phone_digits) <= 15:
            raise HTTPException(status_code=422, detail="Enter a valid phone number with 7 to 15 digits.")
    evidence_types = sorted(set(body.evidence_types))
    if not evidence_types or set(evidence_types) - ALLOWED_EVIDENCE_TYPES:
        raise HTTPException(status_code=422,detail="Choose valid evidence types.")
    token = _issue_token()
    claim_id = uuid.uuid4().hex
    claim_ref = _reference("CL")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _enforce_rate_limit(conn,request,"claim",8)
        lock_row(conn, "reports", "id", report_id)
        report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if not report or report["report_type"] != "found" or report["status"] != "available":
            raise HTTPException(status_code=404,detail="This found item is not available for claims.")
        actor_id = _public_actor_for_roll(conn,roll)
        if report["created_by"] == actor_id:
            raise HTTPException(status_code=403,detail="You cannot claim an item submitted as your own Found report.")
        duplicate = conn.execute(
            "SELECT 1 FROM claims WHERE report_id=? AND claimant_id=? AND status NOT IN ('rejected','returned')",
            (report_id,actor_id),
        ).fetchone()
        if duplicate:
            raise HTTPException(status_code=409,detail="You already have an active claim for this item.")
        # Public roll numbers are attribution only, not authenticated identity.
        # Do not let an unauthenticated visitor exhaust another student's
        # per-student active-claim quota by submitting that student's roll.
        # Anonymous claim volume is bounded by the IP-based rate limiter above.
        lost_report_id = None
        if body.lost_report_reference:
            linked = conn.execute(
                """SELECT id FROM reports WHERE public_ref=? AND report_type='lost' AND status='open'
                   AND created_by=? AND roll_number=? AND submission_channel='public'""",
                (body.lost_report_reference,actor_id,roll),
            ).fetchone()
            if not linked:
                raise HTTPException(status_code=404,detail="The linked Lost report was not found for this roll number.")
            lost_report_id = linked["id"]
        approved_claim = conn.execute(
            "SELECT id FROM claims WHERE report_id=? AND status='approved_for_collection' LIMIT 1",
            (report_id,),
        ).fetchone()
        if approved_claim:
            raise HTTPException(status_code=409, detail="A claim is already approved for collection. No additional claims can be submitted.")
        competing = conn.execute(
            "SELECT id,claimant_id FROM claims WHERE report_id=? AND status IN ('pending','disputed','needs_more_evidence')",
            (report_id,),
        ).fetchall()
        status = "disputed" if competing else "pending"
        timestamp = now_iso()
        conn.execute(
            """INSERT INTO claims
               (id,public_ref,report_id,claimant_id,evidence,evidence_types,status,created_at,updated_at,
                lost_report_id,claimant_roll_number,claimant_phone,tracking_hash,submission_channel)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'public')""",
            (claim_id,claim_ref,report_id,actor_id,body.evidence.strip(),json.dumps(evidence_types, separators=(",", ":")),
             status,timestamp,timestamp,lost_report_id,roll,contact_phone,_hash(token)),
        )
        if competing:
            conn.execute(
                "UPDATE claims SET status='disputed',updated_at=? WHERE report_id=? AND id<>? AND status IN ('pending','disputed','needs_more_evidence')",
                (timestamp,report_id,claim_id),
            )
            for previous in competing:
                notify_user(conn,int(previous["claimant_id"]),"public-claim-dispute:"+report_id,
                            "Competing claim received","Another claim was submitted for this item. The campus office will review all evidence.",
                            "claim",previous["id"])
        audit(conn,actor_id,"public_claim_submitted","claim",claim_id,{"report_id":report_id,"status":status})
        notify_role(conn,"office","public-claim:"+claim_id,"Public claim requires review",
                    "A public claim has been submitted for found item "+report["public_ref"]+".",
                    "claim",claim_id)
        notify_user(conn,actor_id,"public-claim-received:"+claim_id,"Claim received",
                    "Your claim was submitted for office review. Save the private tracking secret shown once.",
                    "claim",claim_id)
    return {
        "claim":{"id":claim_id,"reference":claim_ref,"status":status},
        "tracking_secret":token,
        "message":"Save this tracking secret now. It is shown once.",
    }


@router.post("/claims/{reference}/evidence")
def add_public_claim_evidence(
    reference: str,
    body: PublicEvidenceBody,
    roll_number: str = Header(...,alias="X-LostLink-Roll-Number"),
    tracking_secret: str = Header(...,alias="X-LostLink-Tracking-Secret"),
):
    roll = _roll(roll_number)
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row(conn, "claims", "public_ref", reference)
        claim = conn.execute("SELECT * FROM claims WHERE public_ref=?", (reference,)).fetchone()
        if not claim or claim["submission_channel"] != "public" or claim["claimant_roll_number"] != roll or not _verify_token(claim["tracking_hash"],tracking_secret):
            raise HTTPException(status_code=404,detail="Tracking access not found.")
        if claim["status"] != "needs_more_evidence":
            raise HTTPException(status_code=409,detail="The office has not requested additional evidence.")
        timestamp = now_iso()
        conn.execute(
            "UPDATE claims SET evidence=?,status='pending',updated_at=? WHERE id=?",
            (claim["evidence"]+"\n\nAdditional evidence:\n"+body.evidence.strip(),timestamp,claim["id"]),
        )
        audit(conn,int(claim["claimant_id"]),"public_claim_evidence_added","claim",claim["id"],{})
        notify_role(conn,"office","public-claim-evidence:"+claim["id"],"Additional claim evidence received",
                    "A claimant has supplied the additional evidence requested by the office.",
                    "claim",claim["id"])
    return {"reference":reference,"status":"pending","message":"Additional evidence submitted."}



@router.get("/privacy-export/{reference}")
def export_public_case_data(
    reference: str,
    request: Request,
    roll_number: str = Header(..., alias="X-LostLink-Roll-Number"),
    tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret"),
):
    """Return the data attached to a public case only after its private credentials verify."""
    roll = _roll(roll_number)
    with connect_db() as conn:
        _enforce_rate_limit(conn, request, "privacy-export", 5)
        report = conn.execute("SELECT * FROM reports WHERE public_ref=? AND submission_channel='public'", (reference,)).fetchone()
        if report and report["roll_number"] == roll and _verify_token(report["tracking_hash"], tracking_secret):
            allowed = (
                "public_ref", "report_type", "title", "description", "brand", "primary_color",
                "visible_features", "category", "occurred_at", "location_block", "location_floor",
                "location_room", "location_area", "private_detail", "contact_phone", "contact_email",
                "item_condition", "handover_at", "handover_recipient", "handover_note", "status",
                "created_at", "updated_at", "image_ai_consent",
            )
            return {"type": "report", "data": {key: report[key] for key in allowed if key in report.keys()}}
        claim = conn.execute("SELECT * FROM claims WHERE public_ref=? AND submission_channel='public'", (reference,)).fetchone()
        if claim and claim["claimant_roll_number"] == roll and _verify_token(claim["tracking_hash"], tracking_secret):
            allowed = (
                "public_ref", "evidence", "evidence_types", "status", "reviewer_note",
                "created_at", "updated_at", "claimant_phone",
            )
            return {"type": "claim", "data": {key: claim[key] for key in allowed if key in claim.keys()}}
    raise HTTPException(status_code=404, detail="Private tracking access not found.")


@router.post("/privacy-requests", status_code=201)
def create_public_privacy_request(body: PublicPrivacyRequestBody, request: Request):
    roll = _roll(body.roll_number)
    request_id = uuid.uuid4().hex
    timestamp = now_iso()
    with connect_db() as conn:
        _enforce_rate_limit(conn, request, "privacy", 5)
        report = conn.execute(
            "SELECT roll_number,tracking_hash,contact_email FROM reports WHERE public_ref=? AND submission_channel='public'",
            (body.reference,),
        ).fetchone()
        claim = None
        if not report:
            claim = conn.execute(
                "SELECT claimant_roll_number,tracking_hash,claimant_phone FROM claims WHERE public_ref=? AND submission_channel='public'",
                (body.reference,),
            ).fetchone()
        verified = bool(
            (report and report["roll_number"] == roll and _verify_token(report["tracking_hash"], body.tracking_secret))
            or (claim and claim["claimant_roll_number"] == roll and _verify_token(claim["tracking_hash"], body.tracking_secret))
        )
        if not verified:
            raise HTTPException(status_code=404, detail="Private tracking access not found.")
        requester_email = report["contact_email"] if report else None
        roll_hash = hmac.new(SESSION_SECRET.encode("utf-8"), roll.encode("utf-8"), hashlib.sha256).hexdigest()
        conn.execute(
            """INSERT INTO privacy_requests
               (id,public_reference,requester_email,roll_hash,request_type,details,status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,'pending',?,?)""",
            (request_id, body.reference, requester_email, roll_hash, body.request_type,
             body.details.strip(), timestamp, timestamp),
        )
        actor_id = _public_actor_for_roll(conn, roll)
        audit(conn, actor_id, "public_privacy_request_created", "privacy_request", request_id,
              {"request_type": body.request_type, "public_reference": body.reference})
        notify_role(
            conn, "office", "privacy-request:" + request_id,
            "Public personal-data request received",
            "A verified public case holder submitted a " + body.request_type + " request.",
            "privacy_request", request_id,
        )
    return {"id": request_id, "status": "pending", "message": "Your verified request has been sent to authorised office staff."}

@router.post("/reports/{reference}/ai-consent")
def update_public_ai_consent(
    reference: str,
    body: ImageAiConsentBody,
    request: Request,
    roll_number: str = Header(..., alias="X-LostLink-Roll-Number"),
    tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret"),
):
    roll = _roll(roll_number)
    with connect_db() as conn:
        _enforce_rate_limit(conn, request, "ai-consent", 10)
        lock_row(conn, "reports", "public_ref", reference)
        row = conn.execute(
            "SELECT * FROM reports WHERE public_ref=? AND submission_channel='public'",
            (reference,),
        ).fetchone()
        if not row or row["roll_number"] != roll or not _verify_token(row["tracking_hash"], tracking_secret):
            raise HTTPException(status_code=404, detail="Private tracking access not found.")
        consent = int(bool(body.consent))
        conn.execute(
            """UPDATE reports SET image_ai_consent=?,
               ai_caption=CASE WHEN ?=0 THEN NULL ELSE ai_caption END,
               ai_keywords=CASE WHEN ?=0 THEN NULL ELSE ai_keywords END,
               ai_attributes_json=CASE WHEN ?=0 THEN NULL ELSE ai_attributes_json END,
               ai_enriched_at=CASE WHEN ?=0 THEN NULL ELSE ai_enriched_at END,
               ai_enrichment_model=CASE WHEN ?=0 THEN NULL ELSE ai_enrichment_model END,
               updated_at=? WHERE id=?""",
            (consent, consent, consent, consent, consent, consent, now_iso(), row["id"]),
        )
        if not consent and row["image_sha256"]:
            conn.execute(
                "DELETE FROM ai_embedding_cache WHERE content_hash=? AND model_name LIKE ?",
                (row["image_sha256"], "%:image"),
            )
        audit(conn, int(row["created_by"]), "public_report_image_ai_consent_updated", "report", row["id"],
              {"consent": bool(consent)})
    return {"reference": reference, "image_ai_consent": bool(body.consent)}


