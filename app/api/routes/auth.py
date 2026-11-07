"""HTTP route group."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, HTTPException, Request
from app.core.runtime import *
from app.schemas import *
from app.services.auth import clear_login_failures, login_lockout_remaining, record_failed_login

router = APIRouter()


def _valid_email_address(email: str) -> bool:
    local, separator, domain = email.partition("@")
    return bool(
        separator and local and domain and email.count("@") == 1
        and "." in domain and not any(character.isspace() for character in email)
    )

@router.get("/")
def home():
    return FileResponse(ROOT / "app" / "static" / "index.html")


@router.get("/api/config")
def public_config():
    return {
        "demo_mode": DEMO_MODE,
        "points": POINT_RULES,
        "certificate_milestones": [{"tier": m["tier"], "threshold": m["threshold"]} for m in CERTIFICATE_MILESTONES],
        "categories": [{"value": key, "label": value} for key, value in CATEGORY_LABELS.items()],
        "locations": {
            "blocks": list(CAMPUS_BLOCKS),
            "floors": list(CAMPUS_FLOORS),
            "note": "Campus buildings and floors are deployment-configured. Use the area field for a specific nearby place or detail."
        },
    }


@router.post("/api/office/registration-invites")
def create_registration_invite(
    body: RegistrationInviteBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    require_office(user)
    email = body.email.strip().lower()
    if not _valid_email_address(email):
        raise HTTPException(status_code=422, detail="Enter a valid campus email address.")

    code = secrets.token_urlsafe(32)
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    created_at = now_iso()
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat(timespec="seconds")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account already exists for this email address.")
        # Reissuing an invite invalidates any earlier unused code for the same address.
        conn.execute(
            "UPDATE registration_invites SET used_at=? WHERE email=? AND used_at IS NULL",
            (created_at, email),
        )
        invite_id = uuid.uuid4().hex
        conn.execute(
            """INSERT INTO registration_invites(id, email, code_hash, created_by, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (invite_id, email, code_hash, user["id"], created_at, expires_at),
        )
        audit(conn, user["id"], "student_registration_invite_created", "registration_invite", invite_id,
              {"email": email, "expires_at": expires_at})
    return {
        "email": email,
        "invite_code": code,
        "expires_at": expires_at,
        "message": "One-time registration invite created. Share the code with the verified student through a trusted channel.",
    }


@router.post("/api/register")
def register_student(body: StudentRegistrationBody, request: Request):
    email = body.email.strip().lower()
    display_name = " ".join(body.display_name.split())
    if not _valid_email_address(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    if len(display_name) < 2:
        raise HTTPException(status_code=422, detail="Enter your full name.")

    code_hash = hashlib.sha256(body.invite_code.strip().encode("utf-8")).hexdigest()
    with connect_db() as conn:
        invite = conn.execute(
            """SELECT id FROM registration_invites
               WHERE email=? AND code_hash=? AND used_at IS NULL AND expires_at>?""",
            (email, code_hash, now_iso()),
        ).fetchone()
    if not invite:
        raise HTTPException(status_code=400, detail="The invitation is invalid, expired, or already used.")

    # Validate the invite before paying the password-hashing cost; re-check it
    # inside the write transaction to prevent concurrent reuse.
    password_hash = hash_password(body.password)
    timestamp = now_iso()
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(status_code=409, detail="An account already exists for this email address.")
        invite = conn.execute(
            """SELECT id FROM registration_invites
               WHERE email=? AND code_hash=? AND used_at IS NULL AND expires_at>?""",
            (email, code_hash, timestamp),
        ).fetchone()
        if not invite:
            raise HTTPException(status_code=400, detail="The invitation is invalid, expired, or already used.")
        conn.execute(
            """INSERT INTO users(email, display_name, role, password_hash, created_at)
               VALUES (?, ?, 'student', ?, ?)""",
            (email, display_name, password_hash, timestamp),
        )
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.execute("UPDATE registration_invites SET used_at=? WHERE id=? AND used_at IS NULL",
                     (timestamp, invite["id"]))
        audit(conn, row["id"], "student_registered_with_invite", "user", str(row["id"]),
              {"email": email, "invite_id": invite["id"]})
        user_payload_data = user_payload(row)
    request.session.clear()
    request.session["user_id"] = user_payload_data["id"]
    return {"user": user_payload_data, "message": "Student account created successfully."}


@router.post("/api/login")
def login(body: LoginBody, request: Request):
    email = body.email.strip().lower()
    ip_address = request.client.host if request.client else "unknown"
    subjects = ["email:" + email, "ip:" + ip_address]
    locked_for = 0
    invalid_credentials = False
    user = None
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        locked_for = login_lockout_remaining(conn, subjects)
        if not locked_for:
            row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
            if not row or not verify_password(body.password, row["password_hash"]):
                record_failed_login(conn, subjects)
                invalid_credentials = True
            else:
                clear_login_failures(conn, subjects)
                user = user_payload(row)
    if locked_for:
        raise HTTPException(
            status_code=429,
            detail="Too many sign-in attempts. Try again after the lockout period.",
            headers={"Retry-After": str(locked_for)},
        )
    if invalid_credentials or user is None:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    request.session.clear()
    request.session["user_id"] = user["id"]
    return {"user": user}


@router.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/api/me")
async def me(user: dict[str, Any] = Depends(authenticated_user)):
    return {"user": user}
