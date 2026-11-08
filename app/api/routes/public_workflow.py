"""Public student workflow: roll-number attribution plus private case credentials.

This module is deliberately separate from legacy account-owned reports. A roll
number groups attribution only; it never grants access. Each report/claim gets
a high-entropy tracking secret whose SHA-256 hash alone is stored.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from pydantic import BaseModel, Field

from app.core.runtime import (
    connect_db, now_iso, CATEGORY_LABELS, CATEGORY_DEFAULT_LEVEL, require_office, authenticated_user,
    audit,
)

router = APIRouter(prefix="/api/public", tags=["public-student-workflow"])
ROLL_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{4,19}$")
ACTIVE_CLAIMS = ("pending", "disputed", "needs_more_evidence", "approved_for_collection")


def ensure_public_schema() -> None:
    """Forward-only, independently versioned additive schema for public cases."""
    with connect_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS public_schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS public_cases (
            id TEXT PRIMARY KEY,
            public_ref TEXT NOT NULL UNIQUE,
            report_type TEXT NOT NULL CHECK(report_type IN ('lost','found')),
            roll_number TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT,
            primary_color TEXT,
            visible_features TEXT,
            occurred_at TEXT,
            location_block TEXT,
            location_floor TEXT,
            location_room TEXT,
            location_area TEXT,
            status TEXT NOT NULL,
            tracking_hash TEXT NOT NULL,
            private_detail TEXT,
            tag_id TEXT UNIQUE,
            storage_location TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            intake_by INTEGER,
            intake_at TEXT,
            reviewed_by INTEGER,
            closure_reason TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_public_cases_roll_created
            ON public_cases(roll_number, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_public_cases_browse
            ON public_cases(report_type, status, category, created_at DESC);
        CREATE TABLE IF NOT EXISTS public_claims (
            id TEXT PRIMARY KEY,
            public_ref TEXT NOT NULL UNIQUE,
            case_id TEXT NOT NULL REFERENCES public_cases(id),
            roll_number TEXT NOT NULL,
            evidence TEXT NOT NULL,
            evidence_types TEXT NOT NULL,
            status TEXT NOT NULL,
            tracking_hash TEXT NOT NULL,
            reviewer_id INTEGER,
            reviewer_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_public_claims_case_status
            ON public_claims(case_id, status);
        CREATE INDEX IF NOT EXISTS idx_public_claims_roll_created
            ON public_claims(roll_number, created_at DESC);
        CREATE TABLE IF NOT EXISTS public_rate_limits (
            id TEXT PRIMARY KEY,
            ip_hash TEXT NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_public_rate_limits_lookup ON public_rate_limits(ip_hash,action,created_at);
        CREATE TABLE IF NOT EXISTS public_case_events (
            id TEXT PRIMARY KEY,
            case_id TEXT NOT NULL,
            claim_id TEXT,
            actor_user_id INTEGER,
            event_type TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        """)
        conn.execute(
            "INSERT OR IGNORE INTO public_schema_migrations(version,name,applied_at) VALUES (1,?,?)",
            ("public_roll_attribution_and_tracking_tokens", now_iso()),
        )




def _enforce_rate_limit(conn, request: Request, action: str, maximum: int, window_minutes: int = 60) -> None:
    """Bound anonymous write volume without persisting raw client IP addresses."""
    from datetime import datetime, timedelta, timezone
    address = request.client.host if request.client else "unknown"
    ip_hash = hashlib.sha256(address.encode("utf-8")).hexdigest()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=window_minutes)).isoformat(timespec="seconds")
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM public_rate_limits WHERE ip_hash=? AND action=? AND created_at>=?",
        (ip_hash, action, cutoff),
    ).fetchone()["n"]
    if int(count) >= maximum:
        raise HTTPException(status_code=429, detail="Too many submissions. Please try again later.")
    conn.execute("INSERT INTO public_rate_limits(id,ip_hash,action,created_at) VALUES (?,?,?,?)",
                 (uuid.uuid4().hex, ip_hash, action, now_iso()))


def _roll(value: str) -> str:
    value = value.strip().upper()
    if not ROLL_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail="Enter a valid college roll number.")
    return value


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_token() -> str:
    return secrets.token_urlsafe(32)


def _verify_token(stored_hash: str, token: str | None) -> bool:
    return bool(token) and secrets.compare_digest(stored_hash, _hash(token))


def _ref(prefix: str) -> str:
    return prefix + "-" + secrets.token_hex(4).upper()


def _public_case(row) -> dict[str, Any]:
    return {
        "id": row["id"], "reference": row["public_ref"],
        "report_type": row["report_type"], "title": row["title"],
        "description": row["description"], "category": row["category"],
        "brand": row["brand"], "primary_color": row["primary_color"],
        "visible_features": row["visible_features"],
        "occurred_at": row["occurred_at"], "location_block": row["location_block"],
        "location_area": row["location_area"], "status": row["status"],
        "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def _private_case(row) -> dict[str, Any]:
    result = _public_case(row)
    result.update({"roll_number": row["roll_number"], "location_floor": row["location_floor"],
                   "location_room": row["location_room"], "closure_reason": row["closure_reason"]})
    return result


class PublicReportBody(BaseModel):
    report_type: Literal["lost", "found"]
    roll_number: str = Field(min_length=5, max_length=20)
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


class PublicClaimBody(BaseModel):
    roll_number: str = Field(min_length=5, max_length=20)
    evidence: str = Field(min_length=20, max_length=1800)
    evidence_types: list[str] = Field(min_length=1, max_length=6)


class PublicEvidenceBody(BaseModel):
    evidence: str = Field(min_length=20, max_length=1800)


class PublicCloseBody(BaseModel):
    reason: Literal["recovered_elsewhere", "no_longer_searching", "found_report_withdrawn"]
    note: str | None = Field(default=None, max_length=400)


class StaffIntakeBody(BaseModel):
    confirmed_physical_receipt: bool
    storage_location: str = Field(min_length=3, max_length=160)
    private_detail: str | None = Field(default=None, max_length=1200)
    tag_id: str = Field(min_length=4, max_length=80)


class StaffClaimDecisionBody(BaseModel):
    action: Literal["approve", "reject", "request_more_evidence", "mark_disputed"]
    note: str | None = Field(default=None, max_length=800)
    identity_verified_in_person: bool = False


class StaffHandoverBody(BaseModel):
    tag_id: str = Field(min_length=4, max_length=80)
    confirmed_physical_handover: bool
    claimant_identity_checked: bool


@router.post("/reports", status_code=201)
def submit_public_report(body: PublicReportBody, request: Request):
    roll = _roll(body.roll_number)
    if body.category not in CATEGORY_LABELS:
        raise HTTPException(status_code=422, detail="Choose a valid item category.")
    if not (body.location_block or body.location_area):
        raise HTTPException(status_code=422, detail="Choose a campus block or area.")
    if body.occurred_at:
        from datetime import datetime
        try:
            datetime.fromisoformat(body.occurred_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Use a valid ISO date and time.")
    token = _issue_token()
    case_id, timestamp = uuid.uuid4().hex, now_iso()
    public_ref = _ref("LL")
    status = "open" if body.report_type == "lost" else "awaiting_intake"
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _enforce_rate_limit(conn, request, "report", 10)
        conn.execute(
            """INSERT INTO public_cases
            (id,public_ref,report_type,roll_number,title,description,category,brand,primary_color,
             visible_features,occurred_at,location_block,location_floor,location_room,location_area,
             status,tracking_hash,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (case_id,public_ref,body.report_type,roll,body.title.strip(),body.description.strip(),
             body.category,body.brand,body.primary_color,body.visible_features,body.occurred_at,
             body.location_block,body.location_floor,body.location_room,body.location_area,
             status,_hash(token),timestamp,timestamp),
        )
        conn.execute(
            """INSERT INTO public_case_events(id,case_id,event_type,details_json,created_at)
               VALUES (?,?,?,?,?)""",
            (uuid.uuid4().hex,case_id,"report_submitted",'{"channel":"public"}',timestamp),
        )
    return {"case": {"reference": public_ref, "status": status},
            "tracking_secret": token,
            "message": "Save this tracking secret now. It is shown once and cannot be recovered. Roll number alone never grants access."}


@router.get("/found")
def browse_public_found(category: str | None = None, q: str | None = None, limit: int = 50):
    limit = max(1, min(limit, 100))
    clauses = ["report_type='found'", "status='available'"]
    params: list[Any] = []
    if category and category in CATEGORY_LABELS:
        clauses.append("category=?"); params.append(category)
    if q and q.strip():
        term = "%" + q.strip().lower() + "%"
        clauses.append("(LOWER(title) LIKE ? OR LOWER(description) LIKE ? OR LOWER(COALESCE(location_area,'')) LIKE ?)")
        params.extend([term,term,term])
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM public_cases WHERE " + " AND ".join(clauses) +
                            " ORDER BY created_at DESC LIMIT ?", (*params,limit)).fetchall()
    return {"reports": [_public_case(row) for row in rows]}


@router.get("/track/{reference}")
def track_one_case(reference: str, roll_number: str,
                   tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret")):
    """A bearer secret unlocks only its own case or claim, never all records for a roll number."""
    roll = _roll(roll_number)
    with connect_db() as conn:
        case = conn.execute("SELECT * FROM public_cases WHERE public_ref=?", (reference,)).fetchone()
        if case and case["roll_number"] == roll and _verify_token(case["tracking_hash"], tracking_secret):
            linked_claims = conn.execute(
                "SELECT public_ref,status,created_at FROM public_claims WHERE case_id=? AND roll_number=? ORDER BY created_at",
                (case["id"], roll),
            ).fetchall()
            return {"case": _private_case(case), "claims": [dict(c) for c in linked_claims]}
        claim = conn.execute("SELECT * FROM public_claims WHERE public_ref=?", (reference,)).fetchone()
        if claim and claim["roll_number"] == roll and _verify_token(claim["tracking_hash"], tracking_secret):
            parent = conn.execute("SELECT * FROM public_cases WHERE id=?", (claim["case_id"],)).fetchone()
            return {"claim": {"reference": claim["public_ref"], "status": claim["status"],
                              "evidence": claim["evidence"], "created_at": claim["created_at"]},
                    "item": _public_case(parent)}
    raise HTTPException(status_code=404, detail="Tracking access not found.")


@router.post("/cases/{reference}/close")
def close_public_case(reference: str, body: PublicCloseBody, roll_number: str,
                      tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret")):
    roll = _roll(roll_number)
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM public_cases WHERE public_ref=?", (reference,)).fetchone()
        if not row or row["roll_number"] != roll or not _verify_token(row["tracking_hash"], tracking_secret):
            raise HTTPException(status_code=404, detail="Tracking access not found.")
        if row["report_type"] == "lost" and row["status"] == "open":
            if body.reason == "found_report_withdrawn":
                raise HTTPException(status_code=422, detail="Invalid closure reason for a lost report.")
            status = "closed"
        elif row["report_type"] == "found" and row["status"] == "awaiting_intake":
            if body.reason != "found_report_withdrawn":
                raise HTTPException(status_code=422, detail="A found report can only be withdrawn before office intake.")
            status = "cancelled"
        else:
            raise HTTPException(status_code=409, detail="This case can no longer be closed by its reporter.")
        timestamp = now_iso()
        conn.execute("UPDATE public_cases SET status=?,closure_reason=?,updated_at=? WHERE id=?",
                     (status, body.reason, timestamp, row["id"]))
        conn.execute("INSERT INTO public_case_events(id,case_id,event_type,details_json,created_at) VALUES (?,?,?,?,?)",
                     (uuid.uuid4().hex,row["id"],"report_"+status,'{"reason":"'+body.reason+'"}',timestamp))
    return {"reference": reference, "status": status}


@router.post("/claims/{reference}/evidence")
def add_public_claim_evidence(reference: str, body: PublicEvidenceBody, roll_number: str,
                              tracking_secret: str = Header(..., alias="X-LostLink-Tracking-Secret")):
    roll = _roll(roll_number)
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claim = conn.execute("SELECT * FROM public_claims WHERE public_ref=?", (reference,)).fetchone()
        if not claim or claim["roll_number"] != roll or not _verify_token(claim["tracking_hash"], tracking_secret):
            raise HTTPException(status_code=404, detail="Tracking access not found.")
        if claim["status"] != "needs_more_evidence":
            raise HTTPException(status_code=409, detail="The office has not requested additional evidence.")
        competing = conn.execute(
            "SELECT COUNT(*) AS n FROM public_claims WHERE case_id=? AND id<>? AND status IN ('pending','disputed','needs_more_evidence')",
            (claim["case_id"],claim["id"]),
        ).fetchone()["n"]
        status = "disputed" if competing else "pending"
        timestamp = now_iso()
        conn.execute("UPDATE public_claims SET evidence=?,status=?,updated_at=? WHERE id=?",
                     (body.evidence.strip(),status,timestamp,claim["id"]))
        if competing:
            conn.execute("UPDATE public_claims SET status='disputed',updated_at=? WHERE case_id=? AND status IN ('pending','disputed','needs_more_evidence')",
                         (timestamp,claim["case_id"]))
        conn.execute("INSERT INTO public_case_events(id,case_id,claim_id,event_type,created_at) VALUES (?,?,?,?,?)",
                     (uuid.uuid4().hex,claim["case_id"],claim["id"],"claim_evidence_added",timestamp))
    return {"reference": reference, "status": status}


@router.post("/found/{case_id}/claims", status_code=201)
def submit_public_claim(case_id: str, body: PublicClaimBody, request: Request):
    roll = _roll(body.roll_number)
    allowed = {"distinctive_features","date_location","physical_inspection","supporting_evidence",
               "owner_specific_detail","authorised_record"}
    if set(body.evidence_types) - allowed:
        raise HTTPException(status_code=422, detail="Unknown evidence type.")
    token = _issue_token()
    claim_id, timestamp = uuid.uuid4().hex, now_iso()
    claim_ref = _ref("CL")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _enforce_rate_limit(conn, request, "claim", 20)
        case = conn.execute("SELECT * FROM public_cases WHERE id=?", (case_id,)).fetchone()
        if not case or case["report_type"] != "found" or case["status"] != "available":
            raise HTTPException(status_code=404, detail="Found item is not available for claims.")
        if case["roll_number"] == roll:
            raise HTTPException(status_code=409, detail="A reporter cannot claim their own found-item report.")
        active = conn.execute("SELECT COUNT(*) AS n FROM public_claims WHERE case_id=? AND status IN ('pending','disputed','needs_more_evidence','approved_for_collection')", (case_id,)).fetchone()["n"]
        status = "disputed" if active else "pending"
        conn.execute(
            """INSERT INTO public_claims(id,public_ref,case_id,roll_number,evidence,evidence_types,
               status,tracking_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (claim_id,claim_ref,case_id,roll,body.evidence.strip(),__import__("json").dumps(body.evidence_types),
             status,_hash(token),timestamp,timestamp),
        )
        if active:
            conn.execute("UPDATE public_claims SET status='disputed',updated_at=? WHERE case_id=? AND status IN ('pending','disputed','needs_more_evidence')", (timestamp,case_id))
        conn.execute("UPDATE public_cases SET status='claim_hold',updated_at=? WHERE id=?", (timestamp,case_id))
        conn.execute("INSERT INTO public_case_events(id,case_id,claim_id,event_type,created_at) VALUES (?,?,?,?,?)",
                     (uuid.uuid4().hex,case_id,claim_id,"claim_submitted",timestamp))
    return {"claim": {"reference": claim_ref, "status": status},
            "tracking_secret": token,
            "message": "Save this claim tracking secret now. It is shown once."}


@router.get("/office/cases/{case_id}")
def public_office_case_detail(case_id: str, user: dict[str, Any] = Depends(authenticated_user)):
    require_office(user)
    with connect_db() as conn:
        row = conn.execute("SELECT * FROM public_cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Case not found.")
        claims = conn.execute("SELECT id,public_ref,roll_number,evidence,evidence_types,status,created_at FROM public_claims WHERE case_id=? ORDER BY created_at", (case_id,)).fetchall()
    data = _private_case(row)
    data.update({"private_detail": row["private_detail"], "tag_id": row["tag_id"],
                 "storage_location": row["storage_location"], "intake_at": row["intake_at"],
                 "claims": [dict(c) for c in claims]})
    return {"case": data}


@router.get("/office/intake-queue")
def public_intake_queue(user: dict[str, Any] = Depends(authenticated_user)):
    require_office(user)
    with connect_db() as conn:
        rows = conn.execute("SELECT * FROM public_cases WHERE report_type='found' AND status='awaiting_intake' ORDER BY created_at").fetchall()
    return {"reports": [{"id":r["id"],"reference":r["public_ref"],"title":r["title"],
                         "description":r["description"],"roll_number":r["roll_number"],
                         "created_at":r["created_at"],"location_area":r["location_area"]} for r in rows]}


@router.post("/office/{case_id}/intake")
def confirm_public_intake(case_id: str, body: StaffIntakeBody, user: dict[str, Any] = Depends(authenticated_user)):
    require_office(user)
    if not body.confirmed_physical_receipt:
        raise HTTPException(status_code=422, detail="Confirm that the physical item is in campus custody.")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM public_cases WHERE id=?", (case_id,)).fetchone()
        if not row or row["report_type"] != "found" or row["status"] != "awaiting_intake":
            raise HTTPException(status_code=409, detail="This report is not awaiting intake.")
        timestamp = now_iso()
        conn.execute("""UPDATE public_cases SET status='available',storage_location=?,private_detail=?,
                     tag_id=?,intake_by=?,intake_at=?,updated_at=? WHERE id=?""",
                     (body.storage_location.strip(),body.private_detail,body.tag_id.strip(),user["id"],timestamp,timestamp,case_id))
        conn.execute("INSERT INTO public_case_events(id,case_id,actor_user_id,event_type,created_at) VALUES (?,?,?,?,?)",
                     (uuid.uuid4().hex,case_id,user["id"],"physical_intake_confirmed",timestamp))
        audit(conn,user["id"],"public_case_intake_confirmed","public_case",case_id,{"tag_id":body.tag_id.strip()})
    return {"reference": row["public_ref"], "status":"available",
            "message":"Physical intake recorded. The item is now eligible for public browsing."}


@router.get("/office/claims")
def public_claim_queue(user: dict[str, Any] = Depends(authenticated_user)):
    require_office(user)
    with connect_db() as conn:
        rows = conn.execute("""SELECT c.id,c.public_ref,c.case_id,c.roll_number,c.evidence,c.evidence_types,
                               c.status,c.created_at,p.public_ref AS case_reference,p.title
                               FROM public_claims c JOIN public_cases p ON p.id=c.case_id
                               WHERE c.status IN ('pending','disputed','needs_more_evidence')
                               ORDER BY c.created_at""").fetchall()
    return {"claims":[dict(r) for r in rows]}


@router.post("/office/claims/{claim_id}/decision")
def decide_public_claim(claim_id: str, body: StaffClaimDecisionBody, user: dict[str, Any] = Depends(authenticated_user)):
    require_office(user)
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claim=conn.execute("SELECT * FROM public_claims WHERE id=?",(claim_id,)).fetchone()
        if not claim:
            raise HTTPException(status_code=404,detail="Claim not found.")
        if claim["status"] not in ("pending","disputed","needs_more_evidence"):
            raise HTTPException(status_code=409,detail="Claim is no longer reviewable.")
        others=conn.execute("SELECT COUNT(*) AS n FROM public_claims WHERE case_id=? AND id<>? AND status IN ('pending','disputed','needs_more_evidence','approved_for_collection')",(claim["case_id"],claim_id)).fetchone()["n"]
        if body.action=="approve" and others:
            raise HTTPException(status_code=409,detail="Competing claims must be resolved before approval.")
        if body.action=="approve":
            if not body.identity_verified_in_person:
                raise HTTPException(status_code=422,detail="Office staff must confirm identity in person before approval.")
            allowed_checks={"distinctive_features","date_location","physical_inspection",
                            "supporting_evidence","owner_specific_detail","authorised_record"}
            checked=set(body.verification_checks)
            if checked-allowed_checks:
                raise HTTPException(status_code=422,detail="Unknown verification check.")
            level=int(CATEGORY_DEFAULT_LEVEL.get(conn.execute(
                "SELECT category FROM public_cases WHERE id=?",(claim["case_id"],)
            ).fetchone()["category"],3))
            required={1:2,2:3,3:4,4:4}.get(level,4)
            if len(checked)<required:
                raise HTTPException(status_code=422,detail=f"Verification level L{level} requires {required} distinct checks.")
            if level>=4 and "authorised_record" not in checked:
                raise HTTPException(status_code=422,detail="Restricted items require an authorised record/custodian check.")
        status={"approve":"approved_for_collection","reject":"rejected",
                "request_more_evidence":"needs_more_evidence","mark_disputed":"disputed"}[body.action]
        timestamp=now_iso()
        conn.execute("UPDATE public_claims SET status=?,reviewer_id=?,reviewer_note=?,updated_at=? WHERE id=?",
                     (status,user["id"],body.note,timestamp,claim_id))
        remaining = conn.execute(
            "SELECT COUNT(*) AS n FROM public_claims WHERE case_id=? AND status IN ('pending','disputed','needs_more_evidence','approved_for_collection')",
            (claim["case_id"],),
        ).fetchone()["n"]
        case_status = "claim_approved" if status=="approved_for_collection" else ("claim_hold" if remaining else "available")
        conn.execute("UPDATE public_cases SET status=?,updated_at=? WHERE id=?",
                     (case_status,timestamp,claim["case_id"]))
        conn.execute("INSERT INTO public_case_events(id,case_id,claim_id,actor_user_id,event_type,created_at) VALUES (?,?,?,?,?,?)",
                     (uuid.uuid4().hex,claim["case_id"],claim_id,user["id"],"claim_"+status,timestamp))
        audit(conn,user["id"],"public_claim_decision","public_claim",claim_id,{"decision":body.action,"status":status})
    return {"claim_id":claim_id,"status":status,"message":"Review decision recorded. Physical handover remains a separate office action."}


@router.post("/office/claims/{claim_id}/handover")
def record_public_handover(claim_id: str, body: StaffHandoverBody,
                           user: dict[str, Any] = Depends(authenticated_user)):
    require_office(user)
    if not body.confirmed_physical_handover or not body.claimant_identity_checked:
        raise HTTPException(status_code=422, detail="Confirm claimant identity and physical handover.")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claim=conn.execute("SELECT * FROM public_claims WHERE id=?",(claim_id,)).fetchone()
        if not claim or claim["status"]!="approved_for_collection":
            raise HTTPException(status_code=409,detail="Only an approved claim can be handed over.")
        case=conn.execute("SELECT * FROM public_cases WHERE id=?",(claim["case_id"],)).fetchone()
        if not secrets.compare_digest(str(body.tag_id).strip(),str(case["tag_id"] or "")):
            raise HTTPException(status_code=422,detail="Tag ID does not match the office record.")
        timestamp=now_iso()
        conn.execute("UPDATE public_claims SET status='returned',updated_at=? WHERE id=?",(timestamp,claim_id))
        conn.execute("UPDATE public_cases SET status='returned',updated_at=? WHERE id=?",(timestamp,case["id"]))
        conn.execute("INSERT INTO public_case_events(id,case_id,claim_id,actor_user_id,event_type,created_at) VALUES (?,?,?,?,?,?)",
                     (uuid.uuid4().hex,case["id"],claim_id,user["id"],"physical_handover_recorded",timestamp))
        audit(conn,user["id"],"public_physical_handover","public_claim",claim_id,{"case_id":case["id"]})
    return {"claim_id":claim_id,"status":"returned","message":"Physical handover recorded."}
