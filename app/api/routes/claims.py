"""HTTP route group."""
from fastapi import APIRouter
from app.core.runtime import *
from app.schemas import *
from app.services.object_storage import delete_upload, read_upload, save_upload

router = APIRouter()

@router.post("/api/claims")
async def create_claim(body: ClaimBody, user: dict[str, Any] = Depends(authenticated_user)):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Claims must be submitted from a student account.")
    if any(item not in ALLOWED_EVIDENCE_TYPES for item in body.evidence_types):
        raise HTTPException(status_code=422, detail="Choose valid ownership evidence types.")
    if len(set(body.evidence_types)) != len(body.evidence_types):
        raise HTTPException(status_code=422, detail="Do not select the same evidence type twice.")
    evidence_types = list(body.evidence_types)
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        report = read_report(conn, body.report_id)
        if report["report_type"] != "found" or report["status"] != "available":
            raise HTTPException(status_code=409, detail="This item is not accepting claims.")
        linked_lost = None
        if body.lost_report_id:
            linked_lost = read_report(conn, body.lost_report_id)
            if (linked_lost["report_type"] != "lost" or
                    linked_lost["created_by"] != user["id"] or
                    linked_lost["status"] != "open"):
                raise HTTPException(
                    status_code=409,
                    detail="Choose one of your own open lost reports to link this claim, or leave the link blank."
                )
            existing_linked = conn.execute(
                """SELECT id FROM claims WHERE lost_report_id=?
                   AND status IN ('pending','disputed','needs_more_evidence','approved_for_collection')""",
                (body.lost_report_id,),
            ).fetchone()
            if existing_linked:
                raise HTTPException(
                    status_code=409,
                    detail="That lost report is already linked to a claim under review. Resolve it before starting another claim for the same lost report."
                )
        if report["created_by"] == user["id"]:
            raise HTTPException(status_code=400, detail="You cannot claim your own found-item report.")
        existing_own = conn.execute(
            "SELECT id, status FROM claims WHERE report_id=? AND claimant_id=? AND status IN ('pending','disputed','needs_more_evidence','approved_for_collection','rejected')",
            (body.report_id, user["id"])
        ).fetchone()
        if existing_own:
            if existing_own["status"] == "rejected":
                raise HTTPException(
                    status_code=409,
                    detail="Your previous claim was not approved. Use the one-time review request on My Claims instead of submitting another claim."
                )
            raise HTTPException(status_code=409, detail="You already have an active claim for this item.")
        open_claim_count = conn.execute(
            """SELECT COUNT(*) FROM claims WHERE claimant_id=?
               AND status IN ('pending','disputed','needs_more_evidence','approved_for_collection')""",
            (user["id"],),
        ).fetchone()[0]
        if open_claim_count >= MAX_OPEN_CLAIMS_PER_STUDENT:
            raise HTTPException(
                status_code=409,
                detail=f"You have reached the limit of {MAX_OPEN_CLAIMS_PER_STUDENT} open claims. Wait for a review or use the existing claim's follow-up controls.",
            )
        active = conn.execute(
            "SELECT id FROM claims WHERE report_id=? AND status IN ('pending','disputed','needs_more_evidence')",
            (body.report_id,)
        ).fetchall()
        status = "disputed" if active else "pending"
        claim_id = uuid.uuid4().hex
        timestamp = now_iso()
        conn.execute(
            """INSERT INTO claims(id, report_id, lost_report_id, claimant_id, evidence, evidence_types, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (claim_id, body.report_id, body.lost_report_id, user["id"], body.evidence.strip(),
             json.dumps(evidence_types), status, timestamp, timestamp),
        )
        if active:
            conn.execute(
                "UPDATE claims SET status='disputed', updated_at=? WHERE report_id=? AND status IN ('pending','disputed','needs_more_evidence')",
                (timestamp, body.report_id),
            )
        audit(conn, user["id"], "claim_submitted", "claim", claim_id,
              {"report_id": body.report_id, "competing_claims": bool(active)})
        notify_role(conn, "office", "claim-submitted:" + claim_id, "Ownership claim requires review",
                    "A new ownership claim was submitted for item " + report["public_ref"] + ".", "claim", claim_id)
        if active:
            previous = conn.execute(
                "SELECT DISTINCT claimant_id, id FROM claims WHERE report_id=? AND id<>? AND status='disputed'",
                (body.report_id, claim_id)
            ).fetchall()
            for previous_claim in previous:
                notify_user(
                    conn, previous_claim["claimant_id"],
                    "claim-dispute:" + previous_claim["id"] + ":" + claim_id,
                    "A competing claim was submitted",
                    "This item is on hold while authorised office staff review the competing claims.",
                    "claim", previous_claim["id"]
                )
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    return {"claim": {"id": claim["id"], "status": claim["status"], "created_at": claim["created_at"],
                      "report": serialise_report(report), "message": "Claim submitted for review."}}



@router.post("/api/claims/{claim_id}/evidence-image")
async def upload_claim_evidence_image(
    claim_id: str,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(authenticated_user),
):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only the claimant can add an ownership-evidence image.")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Evidence images must be 5 MB or smaller.")
    normalized, image_sha256, image_phash = canonicalise_image(raw)

    image_key = None
    try:
        with connect_db() as conn:
            # Serialize duplicate checks across simultaneous student and office processes.
            conn.execute("BEGIN IMMEDIATE")
            claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
            if not claim or claim["claimant_id"] != user["id"]:
                raise HTTPException(status_code=404, detail="Claim not found.")
            if claim["status"] not in {"pending", "disputed", "needs_more_evidence"}:
                raise HTTPException(status_code=409, detail="Evidence images can only be added while a claim is under review.")
            if conn.execute("SELECT 1 FROM claim_evidence_images WHERE claim_id=?", (claim_id,)).fetchone():
                raise HTTPException(status_code=409, detail="This claim already has an evidence image attached.")
            if image_fingerprint_matches(conn, image_sha256, image_phash):
                raise HTTPException(
                    status_code=409,
                    detail="This image duplicates or closely matches an image already in LostLink. Use a different, genuine proof image or explain another owner-only detail in text.",
                )
            filename = "claim-" + uuid.uuid4().hex + ".jpg"
            image_key = save_upload(filename, normalized)
            conn.execute(
                """INSERT INTO claim_evidence_images
                   (id, claim_id, uploader_id, image_path, image_sha256, image_phash, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (uuid.uuid4().hex, claim_id, user["id"], image_key, image_sha256, image_phash, now_iso()),
            )
            audit(conn, user["id"], "claim_evidence_image_added", "claim", claim_id,
                  {"sha256_prefix": image_sha256[:12]})
            notify_role(conn, "office", "claim-evidence-image:" + claim_id,
                        "Claim evidence image submitted", "A claimant attached private image evidence for review.",
                        "claim", claim_id)
    except Exception:
        # Also catches commit failures from the connection context manager.
        if image_key is not None:
            try:
                delete_upload(image_key)
            except Exception:
                pass
        raise
    return {"ok": True, "message": "Private evidence image attached."}

@router.get("/api/claims/{claim_id}/evidence-image")
async def get_claim_evidence_image(
    claim_id: str,
    user: dict[str, Any] = Depends(authenticated_user),
):
    with connect_db() as conn:
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found.")
        if user["role"] != "office" and claim["claimant_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Evidence image not available.")
        image_row = conn.execute(
            "SELECT image_path FROM claim_evidence_images WHERE claim_id=?", (claim_id,)
        ).fetchone()
    if not image_row:
        raise HTTPException(status_code=404, detail="No evidence image is attached.")
    try:
        raw_image = read_upload(image_row["image_path"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Evidence image not found.")
    headers = {
        "Cache-Control": "private, no-store",
        "Content-Disposition": "inline",
        "X-Content-Type-Options": "nosniff",
    }
    label = "PRIVATE CLAIM " + claim_id[:8].upper()
    return StreamingResponse(BytesIO(watermark_image(raw_image, label)),
                             media_type="image/jpeg", headers=headers)


@router.get("/api/claims")
async def list_claims(
    page_size: int = 50,
    cursor: str | None = None,
    queue: str = "all",
    user: dict[str, Any] = Depends(authenticated_user),
):
    import base64
    import json as json_module

    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page_size must be between 1 and 100.")
    if queue not in {"all", "disputed", "pending", "active", "handover", "other"}:
        raise HTTPException(status_code=422, detail="queue must be all, disputed, pending, active, handover, or other.")
    internal = user["role"] == "office"
    if not internal and queue != "all":
        raise HTTPException(status_code=403, detail="Queue filters are available to office staff only.")

    cursor_values = None
    if cursor:
        try:
            padded = cursor + ("=" * (-len(cursor) % 4))
            decoded = json_module.loads(base64.urlsafe_b64decode(padded.encode()).decode())
            if (not isinstance(decoded, list) or len(decoded) != 2
                    or not all(isinstance(value, str) for value in decoded)):
                raise ValueError("invalid cursor")
            cursor_values = decoded
        except (ValueError, TypeError, UnicodeDecodeError, json_module.JSONDecodeError):
            raise HTTPException(status_code=400, detail="Invalid claim pagination cursor.")

    where = []
    params: list[Any] = []
    if internal:
        if queue == "disputed":
            where.append("c.status='disputed'")
        elif queue == "pending":
            where.append("c.status='pending'")
        elif queue == "active":
            where.append("c.status IN ('pending','disputed','needs_more_evidence')")
        elif queue == "handover":
            where.append("c.status='approved_for_collection'")
        elif queue == "other":
            where.append("c.status NOT IN ('disputed','pending','needs_more_evidence','approved_for_collection')")
    else:
        where.append("c.claimant_id=?")
        params.append(user["id"])

    # Cursor order is immutable with respect to workflow state. Office priority is
    # exposed as metadata and can be consumed as separate status queues without
    # allowing a status transition to move a row across the active cursor.
    if cursor_values is not None:
        if internal:
            where.append("(c.created_at > ? OR (c.created_at = ? AND c.id > ?))")
        else:
            where.append("(c.created_at < ? OR (c.created_at = ? AND c.id < ?))")
        params.extend([cursor_values[0], cursor_values[0], cursor_values[1]])

    sql = """SELECT c.*, u.display_name AS claimant_name, u.email AS claimant_email
             FROM claims c JOIN users u ON u.id=c.claimant_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += (" ORDER BY c.created_at ASC, c.id ASC" if internal
            else " ORDER BY c.created_at DESC, c.id DESC")
    sql += " LIMIT ?"
    params.append(page_size + 1)

    with connect_db() as conn:
        active_count = 0
        if not internal:
            count_row = conn.execute(
                "SELECT COUNT(*) AS n FROM claims WHERE claimant_id=? AND status IN ('pending','disputed','needs_more_evidence')",
                (user["id"],),
            ).fetchone()
            active_count = int(count_row["n"])
        rows = conn.execute(sql, params).fetchall()
        has_more = len(rows) > page_size
        if has_more:
            rows = rows[:page_size]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            raw = json_module.dumps(
                [str(last["created_at"]), str(last["id"])], separators=(",", ":")
            ).encode()
            next_cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")

        output = []
        for claim in rows:
            report = read_report(conn, claim["report_id"])
            linked_lost_report = None
            if claim["lost_report_id"]:
                linked_row = read_report(conn, claim["lost_report_id"])
                linked_lost_report = {
                    "id": linked_row["id"],
                    "public_ref": linked_row["public_ref"],
                    "title": linked_row["title"],
                    "status": linked_row["status"],
                }
            try:
                evidence_types = json_module.loads(claim["evidence_types"] or "[]")
            except (TypeError, ValueError):
                evidence_types = []
            evidence_image = conn.execute(
                "SELECT 1 FROM claim_evidence_images WHERE claim_id=?", (claim["id"],)
            ).fetchone()
            entry = {
                "id": claim["id"],
                "status": claim["status"],
                "priority_rank": 0 if claim["status"] == "disputed" else (1 if claim["status"] == "pending" else 2),
                "evidence_types": evidence_types,
                "evidence_image_available": evidence_image is not None,
                "created_at": claim["created_at"],
                "updated_at": claim["updated_at"],
                "appeal_note": claim["appeal_note"],
                "appeal_count": claim["appeal_count"],
                "linked_lost_report": linked_lost_report,
                "report": serialise_report(report, internal=internal),
            }
            if internal:
                entry.update({
                    "evidence": claim["evidence"],
                    "claimant_name": claim["claimant_name"],
                    "claimant_email": claim["claimant_email"],
                    "claimant_roll_number": claim["claimant_roll_number"],
                    "submission_channel": claim["submission_channel"],
                    "public_ref": claim["public_ref"],
                    "reviewer_note": claim["reviewer_note"],
                })
            output.append(entry)
    return {
        "claims": output,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "queue": queue if internal else "mine",
        "active_count": active_count if not internal else None,
    }


@router.post("/api/claims/{claim_id}/evidence")
async def update_claim_evidence(
    claim_id: str,
    body: ClaimEvidenceBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="This action is available to the claimant.")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not claim or claim["claimant_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Claim not found.")
        if claim["status"] != "needs_more_evidence":
            raise HTTPException(status_code=409, detail="Additional evidence is not currently requested.")
        active_other = conn.execute(
            "SELECT id FROM claims WHERE report_id=? AND id<>? AND status IN ('pending','disputed','needs_more_evidence')",
            (claim["report_id"], claim_id)
        ).fetchall()
        status = "disputed" if active_other else "pending"
        conn.execute("UPDATE claims SET evidence=?, status=?, updated_at=? WHERE id=?",
                     (body.evidence.strip(), status, now_iso(), claim_id))
        if active_other:
            conn.execute(
                "UPDATE claims SET status='disputed', updated_at=? WHERE report_id=? AND status IN ('pending','disputed','needs_more_evidence')",
                (now_iso(), claim["report_id"])
            )
        audit(conn, user["id"], "claim_evidence_updated", "claim", claim_id)
        notify_role(conn, "office", "claim-evidence:" + claim_id + ":" + now_iso()[:16],
                    "Additional claim evidence submitted", "A claimant has added the requested evidence.", "claim", claim_id)
        updated = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        report = read_report(conn, updated["report_id"])
    return {"claim": {"id": updated["id"], "status": updated["status"],
                      "report": serialise_report(report), "message": "Additional evidence submitted."}}


@router.post("/api/claims/{claim_id}/dispute")
async def dispute_rejected_claim(
    claim_id: str,
    body: ClaimDisputeBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only a student claimant can request a review.")
    reason = body.reason.strip()
    if len(reason) < 20:
        raise HTTPException(status_code=422, detail="Explain why the decision should be reviewed (at least 20 characters).")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not claim or claim["claimant_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Claim not found.")
        if claim["status"] != "rejected":
            raise HTTPException(status_code=409, detail="Only a rejected claim can be disputed by its claimant.")
        if int(claim["appeal_count"] or 0) >= 1:
            raise HTTPException(status_code=409, detail="This claim has already used its one review request.")
        report = read_report(conn, claim["report_id"])
        if report["status"] != "available":
            raise HTTPException(status_code=409, detail="The item is no longer available for another claim review.")
        timestamp = now_iso()
        conn.execute(
            "UPDATE claims SET status='disputed', appeal_note=?, appeal_count=appeal_count+1, updated_at=? WHERE id=?",
            (reason, timestamp, claim_id),
        )
        audit(conn, user["id"], "claim_decision_disputed", "claim", claim_id,
              {"reason": reason, "appeal_count": 1})
        notify_role(conn, "office", "claim-appeal:" + claim_id, "Claim decision review requested",
                    "A claimant has requested a review of a rejected claim for item " + report["public_ref"] + ".",
                    "claim", claim_id)
        notify_user(conn, user["id"], "claim-appeal-confirmation:" + claim_id,
                    "Review request submitted", "Your claim decision has been sent to the campus office for review.",
                    "claim", claim_id)
        updated = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    return {"claim": {"id": updated["id"], "status": updated["status"]},
            "message": "Review request submitted. Your claim is marked disputed until office staff review it."}


@router.post("/api/claims/{claim_id}/decision")
async def decide_claim(
    claim_id: str,
    body: ClaimDecisionBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    require_office(user)
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found.")
        report = read_report(conn, claim["report_id"])
        if claim["status"] in {"rejected", "approved_for_collection", "returned"}:
            raise HTTPException(status_code=409, detail="This claim has already reached a final review state.")
        if body.action == "approve":
            if claim["submission_channel"] == "public":
                verified_roll = (body.verified_roll_number or "").strip().upper()
                if not body.identity_verified_in_person or verified_roll != (claim["claimant_roll_number"] or "").strip().upper():
                    raise HTTPException(status_code=422, detail="Physically verify the claimant's college ID and matching roll number before approving this public claim.")
            # A linked lost report must remain open until the claim is approved.
            # The transaction lock makes this check atomic with report closure.
            if claim["lost_report_id"]:
                linked_lost = read_report(conn, claim["lost_report_id"])
                if (linked_lost["created_by"] != claim["claimant_id"] or
                        linked_lost["report_type"] != "lost" or
                        linked_lost["status"] != "open"):
                    raise HTTPException(
                        status_code=409,
                        detail="The linked lost report is no longer open. Reconcile the report before approving this claim.",
                    )
            others = conn.execute(
                "SELECT id FROM claims WHERE report_id=? AND id<>? AND status IN ('pending','disputed','needs_more_evidence')",
                (claim["report_id"], claim_id)
            ).fetchall()
            if others:
                raise HTTPException(status_code=409, detail="Other active claims exist. Resolve the competing claims before approving this one.")
            if report["status"] not in {"available"}:
                raise HTTPException(status_code=409, detail="The item is not available for claim approval.")
            allowed_checks = {
                "distinctive_features", "date_location", "physical_inspection",
                "supporting_evidence", "owner_specific_detail", "claimant_identity",
                "authorised_record",
            }
            checked = set(body.verification_checks)
            if checked - allowed_checks:
                raise HTTPException(status_code=422, detail="An unknown verification check was submitted.")
            level = int(report["verification_level"] or CATEGORY_DEFAULT_LEVEL.get(report["category"], 3))
            minimum_checks = {1: 2, 2: 3, 3: 4, 4: 4}.get(level, 4)
            if len(checked) < minimum_checks:
                raise HTTPException(status_code=422, detail=f"Verification level L{level} requires at least {minimum_checks} distinct checks.")
            if "claimant_identity" not in checked:
                raise HTTPException(status_code=422, detail="Confirm the claimant's identity before approving the claim.")
            if level >= 4 and "authorised_record" not in checked:
                raise HTTPException(status_code=422, detail="Restricted items require an authorised record/custodian check.")
            new_status = "approved_for_collection"
            conn.execute("UPDATE reports SET status='claim_approved', updated_at=? WHERE id=?",
                         (now_iso(), claim["report_id"]))
        elif body.action == "reject":
            new_status = "rejected"
        elif body.action == "request_more_evidence":
            new_status = "needs_more_evidence"
        else:
            new_status = "disputed"
        conn.execute(
            """UPDATE claims SET status=?, reviewer_id=?, reviewer_note=?, updated_at=? WHERE id=?""",
            (new_status, user["id"], body.note, now_iso(), claim_id),
        )
        if body.action == "approve":
            conn.execute(
                """INSERT OR REPLACE INTO claim_verifications(claim_id, verifier_user_id, checks_json, verified_at)
                   VALUES (?, ?, ?, ?)""",
                (claim_id, user["id"], json.dumps(sorted(checked)), now_iso()),
            )
        audit(conn, user["id"], "claim_review_decision", "claim", claim_id,
              {"decision": body.action, "new_status": new_status,
               "verification_checks": sorted(checked) if body.action == "approve" else []})
        notice_text = {
            "approve": "Your claim passed office verification. The office will complete the physical handover separately.",
            "reject": "Your claim was not approved. Contact the campus office if you believe further review is needed.",
            "request_more_evidence": "The office requested more evidence. Open My Claims to provide the requested information.",
            "mark_disputed": "Your claim is on hold while the office reviews a dispute.",
        }[body.action]
        notice_title = {
            "approve": "Claim verified",
            "reject": "Claim review updated",
            "request_more_evidence": "More evidence requested",
            "mark_disputed": "Claim on hold",
        }[body.action]
        notify_user(conn, claim["claimant_id"], "claim-decision:" + claim_id + ":" + new_status,
                    notice_title, notice_text, "claim", claim_id)
        if body.action == "reject":
            other_active = conn.execute(
                "SELECT 1 FROM claims WHERE report_id=? AND id<>? AND status IN ('pending','disputed','needs_more_evidence')",
                (claim["report_id"], claim_id)
            ).fetchone()
            if not other_active and report["status"] == "available":
                conn.execute("UPDATE reports SET status='available', updated_at=? WHERE id=?", (now_iso(), claim["report_id"]))
        updated = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    return {"claim": {"id": updated["id"], "status": updated["status"]},
            "message": "Claim review updated. Physical collection is not recorded by this module."}




@router.post("/api/claims/{claim_id}/handover")
async def record_handover(
    claim_id: str,
    body: HandoverBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    require_office(user)
    if not body.confirmed_physical_handover or not body.claimant_identity_checked:
        raise HTTPException(status_code=422, detail="Confirm the physical handover and claimant identity.")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        claim = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not claim:
            raise HTTPException(status_code=404, detail="Claim not found.")
        if claim["status"] != "approved_for_collection":
            raise HTTPException(status_code=409, detail="Only an office-verified claim can proceed to handover.")
        report = read_report(conn, claim["report_id"])
        if claim["submission_channel"] == "public":
            verified_roll = (body.verified_roll_number or "").strip().upper()
            if not body.claimant_identity_checked or verified_roll != (claim["claimant_roll_number"] or "").strip().upper():
                raise HTTPException(status_code=422, detail="Physically verify the claimant's college ID and matching roll number before handover.")
        if report["status"] != "claim_approved" or not report["tag_id"]:
            raise HTTPException(status_code=409, detail="The item is not in the approved handover state.")
        if not secrets.compare_digest(str(body.tag_id).strip(), str(report["tag_id"])):
            raise HTTPException(status_code=422, detail="The entered tag ID does not match the office record.")
        timestamp = now_iso()
        conn.execute(
            """INSERT INTO handovers(id, claim_id, report_id, tag_id, claimant_id, office_user_id, handover_note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (uuid.uuid4().hex, claim_id, report["id"], report["tag_id"], claim["claimant_id"],
             user["id"], body.note, timestamp),
        )
        conn.execute("UPDATE claims SET status='returned', reviewer_id=?, updated_at=? WHERE id=?",
                     (user["id"], timestamp, claim_id))
        conn.execute("UPDATE reports SET status='returned', updated_at=? WHERE id=?", (timestamp, report["id"]))
        if claim["lost_report_id"]:
            linked_lost = read_report(conn, claim["lost_report_id"])
            if linked_lost["status"] == "open":
                conn.execute(
                    """UPDATE reports SET status='closed', closure_reason=?, closure_note=?, updated_at=? WHERE id=?""",
                    ("recovered_through_verified_return",
                     "Closed automatically after verified handover of " + report["public_ref"] + ".",
                     timestamp, linked_lost["id"]),
                )
                audit(conn, user["id"], "linked_lost_report_closed_after_return", "report", linked_lost["id"],
                      {"claim_id": claim_id, "found_report_id": report["id"], "tag_id": report["tag_id"]})
                notify_user(
                    conn, claim["claimant_id"], "linked-lost-report-closed:" + linked_lost["id"],
                    "Lost report resolved",
                    "Your linked lost report " + linked_lost["public_ref"] +
                    " was closed automatically after the verified physical handover.",
                    "report", linked_lost["id"],
                )
        audit(conn, user["id"], "physical_handover_recorded", "claim", claim_id,
              {"report_id": report["id"], "tag_id": report["tag_id"]})
        award_points(
            conn, report["created_by"], POINT_RULES["verified_return"],
            "verified-return:" + report["id"],
            "The reported item was returned to a verified owner",
            report["id"], user["id"]
        )
        notify_user(conn, claim["claimant_id"], "handover:" + claim_id, "Item handover recorded",
                    "The campus office recorded the return of the item. The claim is complete.",
                    "claim", claim_id)
        notify_user(conn, report["created_by"], "item-returned:" + report["id"], "A reported item was returned",
                    "The office has completed a verified return associated with your found-item report.",
                    "report", report["id"])
    return {"claim_id": claim_id, "status": "returned", "message": "Physical handover recorded."}
