"""Session authentication and office-role dependency helpers."""
from __future__ import annotations
import sqlite3
from typing import Any
from fastapi import Header, HTTPException, Request
from app.core.database import connect_db, now_iso
from app.core.config import AUTH_PROVIDER, OFFICE_USER_EMAILS
from app.services.supabase_auth import verify_supabase_access_token

def user_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"], "role": row["role"]}


async def authenticated_user(
    request: Request,
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    if AUTH_PROVIDER == "supabase":
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Please sign in.")
        identity = verify_supabase_access_token(token)
        auth_id = str(identity["id"])
        email = str(identity["email"]).strip().lower()
        metadata = identity.get("user_metadata") or {}
        display_name = str(metadata.get("display_name") or metadata.get("full_name") or email.split("@")[0]).strip()[:120]
        with connect_db() as conn:
            row = conn.execute("SELECT * FROM users WHERE supabase_user_id=?", (auth_id,)).fetchone()
            if row is None:
                existing = conn.execute("SELECT * FROM users WHERE lower(email)=?", (email,)).fetchone()
                if existing is not None:
                    if existing["supabase_user_id"] and existing["supabase_user_id"] != auth_id:
                        raise HTTPException(status_code=409, detail="This email is already linked to another identity.")
                    conn.execute("UPDATE users SET supabase_user_id=? WHERE id=?", (auth_id, existing["id"]))
                    row = conn.execute("SELECT * FROM users WHERE id=?", (existing["id"],)).fetchone()
                else:
                    role = "office" if email in OFFICE_USER_EMAILS else "student"
                    conn.execute(
                        """INSERT OR IGNORE INTO users(email, display_name, role, password_hash, created_at, supabase_user_id)
                           VALUES (?, ?, ?, ?, ?, ?)""",
                        (email, display_name or email.split("@")[0], role, "supabase-managed", now_iso(), auth_id),
                    )
                    row = conn.execute("SELECT * FROM users WHERE supabase_user_id=?", (auth_id,)).fetchone()
            if row:
                # Supabase only returns verified emails when confirmation is required.
                # Keep the local profile aligned if the verified email/name changes.
                if row["email"].strip().lower() != email:
                    collision = conn.execute("SELECT id FROM users WHERE lower(email)=?", (email,)).fetchone()
                    if collision and collision["id"] != row["id"]:
                        raise HTTPException(status_code=409, detail="This email is already linked to another LostLink account.")
                    conn.execute("UPDATE users SET email=?, display_name=? WHERE id=?", (email, display_name or email.split("@")[0], row["id"]))
                elif display_name and row["display_name"] != display_name:
                    conn.execute("UPDATE users SET display_name=? WHERE id=?", (display_name, row["id"]))
                # The server-side allowlist is authoritative on every request.
                expected_role = "office" if email in OFFICE_USER_EMAILS else "student"
                if row["role"] != expected_role:
                    conn.execute("UPDATE users SET role=? WHERE id=?", (expected_role, row["id"]))
                row = conn.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="LostLink account could not be provisioned.")
        return user_payload(row)

    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Please sign in.")
    with connect_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Session expired. Please sign in again.")
    return user_payload(row)

def require_office(user: dict[str, Any]) -> None:
    if user["role"] != "office":
        raise HTTPException(status_code=403, detail="Office staff access required.")
