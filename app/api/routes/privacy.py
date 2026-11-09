"""Data-principal access and privacy-request workflow.

Erasure is reviewed by authorised office staff because records may be needed
for active ownership disputes, custody, fraud prevention or legal obligations.
The application never silently deletes an account or case on request.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.runtime import *

router = APIRouter()


class PrivacyRequestBody(BaseModel):
    request_type: Literal["access", "correction", "erasure"]
    details: str = Field(default="", max_length=2000)


class PrivacyDecisionBody(BaseModel):
    action: Literal["in_review", "completed", "declined"]
    note: str = Field(min_length=10, max_length=2000)


@router.get("/api/privacy/export")
async def export_personal_data(user: dict[str, Any] = Depends(authenticated_user)):
    """Export the authenticated user's application data without credential hashes."""
    with connect_db() as conn:
        profile = conn.execute(
            "SELECT id,email,display_name,role,created_at FROM users WHERE id=?",
            (user["id"],),
        ).fetchone()
        reports = conn.execute(
            """SELECT id,public_ref,report_type,title,description,brand,primary_color,
                      visible_features,category,occurred_at,location_block,location_floor,
                      location_room,location_area,private_detail,contact_phone,contact_email,
                      roll_number,image_ai_consent,status,closure_reason,closure_note,
                      tag_id,storage_location,value_band,sensitivity_level,created_at,updated_at
               FROM reports WHERE created_by=? ORDER BY created_at""",
            (user["id"],),
        ).fetchall()
        claims = conn.execute(
            """SELECT id,public_ref,report_id,lost_report_id,evidence,evidence_types,
                      status,appeal_note,appeal_count,reviewer_note,claimant_roll_number,
                      claimant_phone,created_at,updated_at
               FROM claims WHERE claimant_id=? ORDER BY created_at""",
            (user["id"],),
        ).fetchall()
        notifications = conn.execute(
            """SELECT id,title,message,entity_type,entity_id,read_at,created_at
               FROM notifications WHERE user_id=? ORDER BY created_at""",
            (user["id"],),
        ).fetchall()
        rewards = conn.execute(
            """SELECT points,reason,report_id,created_at FROM reward_ledger
               WHERE user_id=? ORDER BY created_at""",
            (user["id"],),
        ).fetchall()
        certificates = conn.execute(
            """SELECT id,tier,threshold_points,points_at_issue,serial,issued_at
               FROM certificates WHERE user_id=? ORDER BY issued_at""",
            (user["id"],),
        ).fetchall()
        requests = conn.execute(
            """SELECT id,request_type,details,status,reviewer_note,created_at,updated_at,completed_at
               FROM privacy_requests WHERE user_id=? ORDER BY created_at""",
            (user["id"],),
        ).fetchall()
    if not profile:
        raise HTTPException(status_code=404, detail="Account not found.")
    return {
        "exported_at": now_iso(),
        "format": "LostLink personal-data export v1",
        "profile": dict(profile),
        "reports": [dict(row) for row in reports],
        "claims": [dict(row) for row in claims],
        "notifications": [dict(row) for row in notifications],
        "reward_ledger": [dict(row) for row in rewards],
        "certificates": [dict(row) for row in certificates],
        "privacy_requests": [dict(row) for row in requests],
        "excluded_security_fields": ["password_hash", "auth_subject", "tracking_hash", "image_path"],
    }


@router.post("/api/privacy/requests", status_code=201)
async def create_privacy_request(
    body: PrivacyRequestBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    request_id = uuid.uuid4().hex
    timestamp = now_iso()
    with connect_db() as conn:
        existing = conn.execute(
            """SELECT id FROM privacy_requests WHERE user_id=?
               AND request_type=? AND status IN ('pending','in_review') LIMIT 1""",
            (user["id"], body.request_type),
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="You already have an open request of this type.")
        conn.execute(
            """INSERT INTO privacy_requests
               (id,user_id,request_type,details,status,created_at,updated_at)
               VALUES (?,?,?,?,'pending',?,?)""",
            (request_id, user["id"], body.request_type, body.details.strip(), timestamp, timestamp),
        )
        audit(conn, user["id"], "privacy_request_created", "privacy_request", request_id,
              {"request_type": body.request_type})
        notify_role(
            conn, "office", "privacy-request:" + request_id,
            "Personal-data request received",
            "An authenticated user submitted a " + body.request_type + " request for office review.",
            "privacy_request", request_id,
        )
    return {"id": request_id, "status": "pending", "message": "Your request has been sent to authorised office staff."}


@router.get("/api/privacy/requests")
async def list_my_privacy_requests(user: dict[str, Any] = Depends(authenticated_user)):
    with connect_db() as conn:
        rows = conn.execute(
            """SELECT id,request_type,details,status,reviewer_note,created_at,updated_at,completed_at
               FROM privacy_requests WHERE user_id=? ORDER BY created_at DESC""",
            (user["id"],),
        ).fetchall()
    return {"requests": [dict(row) for row in rows]}


@router.get("/api/office/privacy-requests")
async def list_privacy_requests(user: dict[str, Any] = Depends(authenticated_user)):
    require_office(user)
    with connect_db() as conn:
        rows = conn.execute(
            """SELECT p.id,p.user_id,p.public_reference,p.requester_email,p.request_type,
                      p.details,p.status,p.reviewer_note,p.created_at,p.updated_at,
                      u.email AS account_email,u.display_name
               FROM privacy_requests p LEFT JOIN users u ON u.id=p.user_id
               ORDER BY CASE p.status WHEN 'pending' THEN 0 WHEN 'in_review' THEN 1 ELSE 2 END,
                        p.created_at ASC LIMIT 200"""
        ).fetchall()
    return {"requests": [dict(row) for row in rows]}


@router.post("/api/office/privacy-requests/{request_id}/decision")
async def decide_privacy_request(
    request_id: str,
    body: PrivacyDecisionBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    require_office(user)
    timestamp = now_iso()
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row(conn, "privacy_requests", "id", request_id) if ("privacy_requests", "id") in _ROW_LOCK_TARGETS else None
        request_row = conn.execute(
            "SELECT * FROM privacy_requests WHERE id=?", (request_id,)
        ).fetchone()
        if not request_row:
            raise HTTPException(status_code=404, detail="Privacy request not found.")
        if request_row["status"] in {"completed", "declined"}:
            raise HTTPException(status_code=409, detail="This privacy request is already closed.")
        completed_at = timestamp if body.action in {"completed", "declined"} else None
        conn.execute(
            """UPDATE privacy_requests SET status=?,reviewed_by=?,reviewer_note=?,
               updated_at=?,completed_at=? WHERE id=?""",
            (body.action, user["id"], body.note.strip(), timestamp, completed_at, request_id),
        )
        audit(conn, user["id"], "privacy_request_" + body.action, "privacy_request", request_id,
              {"request_type": request_row["request_type"]})
        if request_row["user_id"]:
            notify_user(
                conn, request_row["user_id"], "privacy-request-update:" + request_id + ":" + body.action,
                "Update on your personal-data request",
                "Your " + request_row["request_type"] + " request is now " + body.action.replace("_", " ") + ".",
                "privacy_request", request_id,
            )
    return {"id": request_id, "status": body.action, "message": "Privacy request status updated."}
