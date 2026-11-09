"""HTTP route group."""
from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool
from app.core.runtime import *
from app.schemas import *
from app.services.object_storage import delete_upload, read_upload, save_upload

router = APIRouter()

@router.get("/api/reports")
async def list_reports(
    report_type: str | None = None,
    category: str | None = None,
    block: str | None = None,
    room: str | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    status: str | None = None,
    mine: bool = False,
    page_size: int = 50,
    cursor: str | None = None,
    user: dict[str, Any] = Depends(authenticated_user),
):
    import base64
    import json as json_module

    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page_size must be between 1 and 100.")

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
            raise HTTPException(status_code=400, detail="Invalid report pagination cursor.")

    conditions: list[str] = []
    params: list[Any] = []
    internal = user["role"] == "office"

    if not internal and mine:
        conditions.append("r.created_by=?")
        params.append(user["id"])
    elif not internal:
        conditions.extend(["r.report_type='found'", "r.status='available'"])
    elif mine:
        conditions.append("r.created_by=?")
        params.append(user["id"])

    if report_type in {"lost", "found"}:
        conditions.append("r.report_type=?")
        params.append(report_type)
    if category in CATEGORY_LABELS:
        conditions.append("r.category=?")
        params.append(category)
    if block:
        conditions.append("LOWER(COALESCE(r.location_block,'')) LIKE ? ESCAPE '!'")
        params.append("%" + block.lower() + "%")
    if room:
        conditions.append("LOWER(COALESCE(r.location_room,'')) LIKE ? ESCAPE '!'")
        params.append("%" + room.lower() + "%")
    if q:
        term = "%" + q.strip().lower().replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
        conditions.append("""(
            LOWER(r.title) LIKE ? ESCAPE '!' OR LOWER(r.description) LIKE ? ESCAPE '!' OR LOWER(r.public_ref) LIKE ? ESCAPE '!'
            OR LOWER(COALESCE(r.location_area,'')) LIKE ? ESCAPE '!' OR LOWER(COALESCE(r.brand,'')) LIKE ? ESCAPE '!'
            OR LOWER(COALESCE(r.primary_color,'')) LIKE ? ESCAPE '!' OR LOWER(COALESCE(r.visible_features,'')) LIKE ? ESCAPE '!'
            OR LOWER(COALESCE(r.location_block,'')) LIKE ? ESCAPE '!' OR LOWER(COALESCE(r.location_floor,'')) LIKE ? ESCAPE '!'
            OR LOWER(COALESCE(r.location_room,'')) LIKE ? ESCAPE '!'
            OR LOWER(COALESCE(r.ai_caption,'')) LIKE ? ESCAPE '!' OR LOWER(COALESCE(r.ai_keywords,'')) LIKE ? ESCAPE '!'
        )""")
        params.extend([term] * 12)
    if date_from:
        conditions.append("COALESCE(r.occurred_at,'') >= ?")
        params.append(date_from)
    if date_to:
        conditions.append("COALESCE(r.occurred_at,'') <= ?")
        params.append(date_to + "T23:59:59")
    if internal and status:
        statuses = [value.strip() for value in status.split(",") if value.strip()]
        allowed_statuses = {"open", "awaiting_intake", "available", "claim_approved", "returned", "closed", "cancelled"}
        if not statuses or len(statuses) > len(allowed_statuses) or any(value not in allowed_statuses for value in statuses):
            raise HTTPException(status_code=422, detail="status contains an unsupported report status.")
        if len(statuses) == 1:
            conditions.append("r.status=?")
            params.append(statuses[0])
        else:
            conditions.append("r.status IN (" + ",".join("?" for _ in statuses) + ")")
            params.extend(statuses)

    if cursor_values is not None:
        conditions.append("(r.created_at < ? OR (r.created_at = ? AND r.id < ?))")
        params.extend([cursor_values[0], cursor_values[0], cursor_values[1]])

    sql = "SELECT r.* FROM reports r"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY r.created_at DESC, r.id DESC LIMIT ?"
    params.append(page_size + 1)
    with connect_db() as conn:
        rows = conn.execute(sql, params).fetchall()
        has_more = len(rows) > page_size
        if has_more:
            rows = rows[:page_size]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            raw_cursor = json_module.dumps([str(last["created_at"]), str(last["id"])], separators=(",", ":")).encode()
            next_cursor = base64.urlsafe_b64encode(raw_cursor).decode().rstrip("=")
        reports = []
        for row in rows:
            report_data = serialise_report(row, internal=internal)
            if row["report_type"] == "lost" and int(row["created_by"]) == int(user["id"]):
                active_claim = conn.execute(
                    """SELECT 1 FROM claims WHERE lost_report_id=?
                       AND status IN ('pending','disputed','needs_more_evidence','approved_for_collection') LIMIT 1""",
                    (row["id"],),
                ).fetchone()
                report_data["has_active_linked_claim"] = active_claim is not None
            reports.append(report_data)
    return {"reports": reports, "next_cursor": next_cursor, "has_more": has_more}



@router.post("/api/reports/category-suggestion")
async def suggest_report_category(
    body: CategorySuggestionBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    """Suggest a category from public item details; the student must confirm it."""
    from app.services.category_classification import suggest_category

    payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
    result = await run_in_threadpool(suggest_category, payload)
    return {"suggestion": result}


@router.post("/api/reports")
async def create_report(body: ReportBody, user: dict[str, Any] = Depends(authenticated_user)):
    if len(body.title.strip()) < 4:
        raise HTTPException(status_code=422, detail="Enter an item name of at least 4 characters.")
    if len(body.description.strip()) < 10:
        raise HTTPException(status_code=422, detail="Add at least 10 characters describing the item.")
    if body.occurred_at:
        try:
            datetime.fromisoformat(body.occurred_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Use a valid ISO date and time, or leave the date blank if unknown.")
    if body.category not in CATEGORY_LABELS:
        raise HTTPException(status_code=422, detail="Choose a valid item category.")
    if not (body.location_block or body.location_area):
        raise HTTPException(status_code=422, detail="Choose a campus block or area.")
    report_id = uuid.uuid4().hex
    public_ref = new_public_ref()
    timestamp = now_iso()
    status = "open" if body.report_type == "lost" else "awaiting_intake"
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """INSERT INTO reports(id, public_ref, report_type, title, description, brand, primary_color,
               visible_features, category, occurred_at, location_block, location_floor, location_room,
               location_area, image_ai_consent, status, created_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report_id, public_ref, body.report_type, body.title.strip(), body.description.strip(),
             (body.brand or "").strip() or None, (body.primary_color or "").strip() or None,
             (body.visible_features or "").strip() or None, body.category, body.occurred_at,
             body.location_block, body.location_floor, body.location_room, body.location_area,
             int(body.image_ai_consent), status, user["id"], timestamp, timestamp),
        )
        audit(conn, user["id"], "report_created", "report", report_id, {"report_type": body.report_type})
        if body.report_type == "found":
            notify_role(conn, "office", "found-report:" + report_id, "Found-item report awaiting intake",
                        "A new found-item report is waiting for physical office intake.", "report", report_id)
            notify_user(conn, user["id"], "report-created:" + report_id, "Found report submitted",
                        "Your found-item report is waiting for the office to confirm physical receipt.", "report", report_id)
        else:
            notify_user(conn, user["id"], "report-created:" + report_id, "Lost report submitted",
                        "Your lost-item report is saved. LostLink can suggest possible matches as found items are received.", "report", report_id)
            notify_matches_for_lost_report(conn, read_report(conn, report_id))
        lock_row(conn, "reports", "id", report_id)
        row = read_report(conn, report_id)
    return {"report": serialise_report(row, internal=user["role"] == "office"),
            "message": "Lost report submitted." if body.report_type == "lost" else "Found-item report submitted for office intake. It will become searchable after staff confirm receipt."}


@router.put("/api/reports/{report_id}")
async def update_report(
    report_id: str,
    body: ReportBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    """Edit public report details while the report remains in an editable workflow state."""
    if len(body.title.strip()) < 4:
        raise HTTPException(status_code=422, detail="Enter an item name of at least 4 characters.")
    if len(body.description.strip()) < 10:
        raise HTTPException(status_code=422, detail="Add at least 10 characters describing the item.")
    if body.category not in CATEGORY_LABELS:
        raise HTTPException(status_code=422, detail="Choose a valid item category.")
    if not (body.location_block or body.location_area):
        raise HTTPException(status_code=422, detail="Choose a campus block or area.")
    if body.occurred_at:
        try:
            datetime.fromisoformat(body.occurred_at.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(status_code=422, detail="Use a valid ISO date and time, or leave the date blank if unknown.")

    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row(conn, "reports", "id", report_id)
        row = read_report(conn, report_id)
        is_office = user["role"] == "office"
        if not is_office and int(row["created_by"]) != int(user["id"]):
            raise HTTPException(status_code=404, detail="Report not found.")
        if body.report_type != row["report_type"]:
            raise HTTPException(status_code=422, detail="A report's lost/found type cannot be changed after submission.")
        if row["report_type"] == "lost":
            if row["status"] != "open":
                raise HTTPException(status_code=409, detail="Only an open lost report can be edited.")
        elif is_office:
            if row["status"] in {"returned", "cancelled"}:
                raise HTTPException(status_code=409, detail="A completed or cancelled found report cannot be edited.")
        elif row["status"] != "awaiting_intake":
            raise HTTPException(status_code=409, detail="A found report can only be edited by its owner before office intake.")

        timestamp = now_iso()
        conn.execute(
            """UPDATE reports SET title=?, description=?, brand=?, primary_color=?,
               visible_features=?, category=?, occurred_at=?, location_block=?,
               location_floor=?, location_room=?, location_area=?, updated_at=?
               WHERE id=?""",
            (body.title.strip(), body.description.strip(),
             (body.brand or "").strip() or None,
             (body.primary_color or "").strip() or None,
             (body.visible_features or "").strip() or None,
             body.category, body.occurred_at, body.location_block,
             body.location_floor, body.location_room, body.location_area,
             timestamp, report_id),
        )
        audit(conn, user["id"], "report_details_updated", "report", report_id, {
            "report_type": row["report_type"],
            "fields": ["title", "description", "brand", "primary_color",
                       "visible_features", "category", "occurred_at",
                       "location_block", "location_floor", "location_room", "location_area"],
        })
        updated = read_report(conn, report_id)
    return {"report": serialise_report(updated, internal=is_office), "message": "Report details updated."}


@router.post("/api/reports/{report_id}/close")
async def close_report(
    report_id: str,
    body: ReportCloseBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Only the report owner can close their report.")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row(conn, "reports", "id", report_id)
        report = read_report(conn, report_id)
        if report["created_by"] != user["id"]:
            raise HTTPException(status_code=404, detail="Report not found.")
        if report["report_type"] == "lost" and report["status"] == "open":
            linked_active_claim = conn.execute(
                """SELECT 1 FROM claims WHERE lost_report_id=?
                   AND status IN ('pending','disputed','needs_more_evidence','approved_for_collection') LIMIT 1""",
                (report_id,),
            ).fetchone()
            if linked_active_claim:
                raise HTTPException(
                    status_code=409,
                    detail="This lost report is linked to a claim under review. Resolve that claim before closing the report."
                )
            if body.reason == "found_report_withdrawn":
                raise HTTPException(status_code=422, detail="Choose a reason for closing your lost-item search.")
            final_status = "closed"
            title = "Lost report closed"
            message = "Your lost report has been closed. It will no longer generate match suggestions, and its history remains visible in My Reports."
        elif report["report_type"] == "found" and report["status"] == "awaiting_intake":
            if body.reason != "found_report_withdrawn":
                raise HTTPException(status_code=422, detail="A found report can only be withdrawn before office intake.")
            final_status = "cancelled"
            title = "Found report withdrawn"
            message = "Your found report was withdrawn before the campus office accepted physical custody."
        else:
            raise HTTPException(status_code=409, detail="Only an open lost report or a found report awaiting office intake can be closed.")
        timestamp = now_iso()
        conn.execute(
            "UPDATE reports SET status=?, closure_reason=?, closure_note=?, updated_at=? WHERE id=?",
            (final_status, body.reason, (body.note or "").strip() or None, timestamp, report_id),
        )
        audit(conn, user["id"], "report_closed_or_withdrawn", "report", report_id,
              {"report_type": report["report_type"], "status": final_status,
               "reason": body.reason, "note": (body.note or "").strip() or None})
        notify_user(conn, user["id"], "report-closed:" + report_id, title, message, "report", report_id)
        if report["report_type"] == "found":
            notify_role(conn, "office", "found-report-withdrawn:" + report_id,
                        "Found report withdrawn before intake",
                        "A student withdrew a found-item report before the physical item was accepted into campus custody.",
                        "report", report_id)
        updated = read_report(conn, report_id)
    return {"report": serialise_report(updated), "message": title + "."}


@router.post("/api/reports/{report_id}/image")
async def upload_report_image(
    report_id: str,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(authenticated_user),
):
    with connect_db() as conn:
        row = read_report(conn, report_id)
        is_office = user["role"] == "office"
        if not is_office and row["created_by"] != user["id"]:
            raise HTTPException(status_code=403, detail="You cannot update this report.")
        if not is_office and row["report_type"] == "found" and row["status"] != "awaiting_intake":
            raise HTTPException(status_code=409, detail="A found item's photo can only be changed before office intake.")
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Images must be 5 MB or smaller.")
    normalized, image_sha256, image_phash = canonicalise_image(raw)

    filename = uuid.uuid4().hex + ".jpg"
    new_key = None
    old = None
    try:
        # Keep object-storage latency outside the global PostgreSQL write lock.
        new_key = await run_in_threadpool(save_upload, filename, normalized)
        with connect_db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            lock_row(conn, "reports", "id", report_id)
            row = read_report(conn, report_id)
            is_office = user["role"] == "office"
            if not is_office and row["created_by"] != user["id"]:
                raise HTTPException(status_code=403, detail="You cannot update this report.")
            if not is_office and row["report_type"] == "found" and row["status"] != "awaiting_intake":
                raise HTTPException(status_code=409, detail="A found item's photo can only be changed before office intake.")
            if is_office and image_fingerprint_matches(conn, image_sha256, image_phash):
                raise HTTPException(status_code=409, detail="This image cannot be attached. Please choose another image.")
            old = row["image_path"]
            conn.execute(
                "UPDATE reports SET image_path=?, image_sha256=?, image_phash=?, updated_at=? WHERE id=?",
                (new_key, image_sha256, image_phash, now_iso(), report_id),
            )
            audit(conn, user["id"], "report_image_added", "report", report_id)
            updated = read_report(conn, report_id)
    except Exception:
        if new_key is not None:
            try:
                await run_in_threadpool(delete_upload, new_key)
            except Exception:
                pass
        raise

    if old and old != new_key:
        try:
            await run_in_threadpool(delete_upload, old)
        except Exception:
            pass
    return {"report": serialise_report(updated, internal=user["role"] == "office")}



@router.post("/api/reports/{report_id}/ai-consent")
async def update_report_ai_consent(
    report_id: str,
    body: ImageAiConsentBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row(conn, "reports", "id", report_id)
        row = read_report(conn, report_id)
        if user["role"] != "office" and int(row["created_by"]) != int(user["id"]):
            raise HTTPException(status_code=404, detail="Report not found.")
        consent = int(bool(body.consent))
        conn.execute(
            """UPDATE reports SET image_ai_consent=?,
               ai_caption=CASE WHEN ?=0 THEN NULL ELSE ai_caption END,
               ai_keywords=CASE WHEN ?=0 THEN NULL ELSE ai_keywords END,
               ai_attributes_json=CASE WHEN ?=0 THEN NULL ELSE ai_attributes_json END,
               ai_enriched_at=CASE WHEN ?=0 THEN NULL ELSE ai_enriched_at END,
               ai_enrichment_model=CASE WHEN ?=0 THEN NULL ELSE ai_enrichment_model END,
               updated_at=? WHERE id=?""",
            (consent, consent, consent, consent, consent, consent, now_iso(), report_id),
        )
        if not consent and row["image_sha256"]:
            conn.execute(
                "DELETE FROM ai_embedding_cache WHERE content_hash=? AND model_name LIKE ?",
                (row["image_sha256"], "%:image"),
            )
        audit(conn, user["id"], "report_image_ai_consent_updated", "report", report_id,
              {"consent": bool(consent)})
    return {"report_id": report_id, "image_ai_consent": bool(body.consent)}


@router.post("/api/reports/{report_id}/enrichment")
async def enrich_report_image(report_id: str, user: dict[str, Any] = Depends(authenticated_user)):
    """Generate private-to-owner image suggestions; never overwrite student-authored fields."""
    from app.services.image_enrichment import enrich_image

    with connect_db() as conn:
        row = read_report(conn, report_id)
        if user["role"] != "office" and row["created_by"] != user["id"]:
            raise HTTPException(status_code=404, detail="Report not found.")
        if not row["image_path"]:
            raise HTTPException(status_code=409, detail="Upload an item photo before requesting image enrichment.")
        if not row["image_ai_consent"]:
            raise HTTPException(status_code=403, detail="AI photo analysis was not authorised for this report.")
        image_key = row["image_path"]
        try:
            image_bytes = read_upload(image_key)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="The report photo is unavailable.")

    result = await run_in_threadpool(enrich_image, image_bytes)
    if result.get("status") != "completed":
        return {"enrichment": result}
    with connect_db() as conn:
        conn.execute(
            """UPDATE reports SET ai_caption=?, ai_keywords=?, ai_attributes_json=?,
               ai_enriched_at=?, ai_enrichment_model=?, updated_at=? WHERE id=?""",
            (result["caption"], json.dumps(result["keywords"]), json.dumps(result["attributes"]),
             now_iso(), result["model"], now_iso(), report_id),
        )
        audit(conn, user["id"], "report_image_ai_enriched", "report", report_id,
              {"model": result["model"], "keyword_count": len(result["keywords"])})
    return {"enrichment": result}


@router.get("/api/reports/{report_id}/image")
async def get_report_image(report_id: str, user: dict[str, Any] = Depends(authenticated_user)):
    with connect_db() as conn:
        row = read_report(conn, report_id)
    if not row["image_path"]:
        raise HTTPException(status_code=404, detail="No image is available.")
    if user["role"] != "office":
        if not report_visible_to_student(row, user):
            raise HTTPException(status_code=404, detail="Image not available.")
        if row["category"] in SENSITIVE_CATEGORIES:
            raise HTTPException(status_code=404, detail="Images of sensitive items are restricted.")
    try:
        raw_image = read_upload(row["image_path"])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found.")
    headers = {
        "Cache-Control": "private, no-store",
        "Content-Disposition": "inline",
        "X-Content-Type-Options": "nosniff",
    }
    if user["role"] != "office":
        return StreamingResponse(BytesIO(watermark_image(raw_image, row["public_ref"])),
                                 media_type="image/jpeg", headers=headers)
    return StreamingResponse(BytesIO(raw_image), media_type="image/jpeg", headers=headers)


@router.get("/api/reports/{report_id}/matches")
async def get_matches(report_id: str, user: dict[str, Any] = Depends(authenticated_user)):
    from app.matching import matching_engine

    with connect_db() as conn:
        lost = read_report(conn, report_id)
        if lost["report_type"] != "lost":
            raise HTTPException(status_code=400, detail="Matches are generated from a lost-item report.")
        if lost["status"] != "open":
            raise HTTPException(status_code=409, detail="Only an open lost report can be matched.")
        if user["role"] != "office" and lost["created_by"] != user["id"]:
            raise HTTPException(status_code=403, detail="You can only view matches for your own lost reports.")
        # Bounded two-tier retrieval: prioritise same-category records, then
        # reserve capacity for cross-category/location candidates. Both scans use
        # composite indexes added by schema migration v7; scoring remains in the
        # existing category-aware MiniLM/CLIP engine and never scans the full table.
        candidate_limit = MATCHING_CANDIDATE_LIMIT
        category_limit = max(1, int(candidate_limit * 0.75))
        fallback_limit = candidate_limit - category_limit
        candidates_by_id = {}
        if lost["category"]:
            category_rows = conn.execute(
                """SELECT * FROM reports
                   WHERE report_type='found' AND status='available' AND category=?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (lost["category"], category_limit),
            ).fetchall()
            candidates_by_id.update({row["id"]: row for row in category_rows})
            if fallback_limit:
                fallback_match = ["category<>?", "category IS NULL"]
                fallback_params: list[Any] = [lost["category"]]
                if lost["location_block"]:
                    fallback_match.append("LOWER(COALESCE(location_block,''))=LOWER(?)")
                    fallback_params.append(lost["location_block"])
                if lost["location_area"]:
                    fallback_match.append("LOWER(COALESCE(location_area,''))=LOWER(?)")
                    fallback_params.append(lost["location_area"])
                fallback_sql = (
                    "SELECT * FROM reports WHERE report_type='found' AND status='available' "
                    "AND (" + " OR ".join(fallback_match) + ") "
                    "ORDER BY created_at DESC, id DESC LIMIT ?"
                )
                fallback_params.append(fallback_limit)
                fallback_rows = conn.execute(fallback_sql, fallback_params).fetchall()
                candidates_by_id.update({row["id"]: row for row in fallback_rows})
        else:
            recent_rows = conn.execute(
                """SELECT * FROM reports
                   WHERE report_type='found' AND status='available'
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (candidate_limit,),
            ).fetchall()
            candidates_by_id.update({row["id"]: row for row in recent_rows})
        candidates = [
            row for row in candidates_by_id.values()
            if user["role"] == "office" or report_visible_to_student(row, user)
        ]
    lost_for_matching = dict(lost)
    if lost_for_matching.get("image_path"):
        lost_for_matching["image_key"] = lost_for_matching["image_path"]
        lost_for_matching["image_loader"] = read_upload
        lost_for_matching["image_path"] = str(UPLOAD_DIR / lost_for_matching["image_path"])
    candidate_data = []
    for candidate in candidates:
        candidate_item = dict(candidate)
        if candidate_item.get("image_path"):
            candidate_item["image_key"] = candidate_item["image_path"]
            candidate_item["image_loader"] = read_upload
            candidate_item["image_path"] = str(UPLOAD_DIR / candidate_item["image_path"])
        candidate_data.append(candidate_item)
    ranked = await run_in_threadpool(
        matching_engine.rank, lost_for_matching, candidate_data, limit=5
    )
    internal = user["role"] == "office"
    results = []
    # Re-read the top results after model inference: an item may have been
    # claimed, withdrawn, or moved to a restricted workflow state meanwhile.
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
    for match in ranked:
        fresh = fresh_by_id.get(match["report"]["id"])
        if fresh is None or (not internal and not report_visible_to_student(fresh, user)):
            continue
        item = serialise_report(fresh, internal=internal)
        entry = {"report": item, "strength": match["strength"], "reasons": match["reasons"]}
        if internal:
            entry["internal_score"] = match["score"]
            entry["signals"] = match["signals"]
            entry["matching_engine"] = match["engine"]
        results.append(entry)
    response = {
        "matches": results,
        "note": "Suggestions support discovery only; they do not establish ownership.",
    }
    if internal:
        response["candidate_count"] = len(candidates)
        response["candidate_limit"] = MATCHING_CANDIDATE_LIMIT
    return response


@router.get("/api/office/ai-status")
def office_ai_status(user: dict[str, Any] = Depends(authenticated_user)):
    """Office-only diagnostics for the optional matching models."""
    from app.matching import matching_engine
    from app.services.image_enrichment import model_status as image_model_status

    require_office(user)
    return {
        "models": {**matching_engine.model_status(), "image_enrichment": image_model_status()},
        "matching_policy": "AI scores rank candidates for human review; they do not establish ownership.",
        "privacy_policy": "Only public report descriptions and approved report photos are used for discovery. Private claim evidence and office storage details are excluded.",
    }


@router.post("/api/reports/{report_id}/intake")
async def intake_found_item(
    report_id: str,
    body: IntakeBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    require_office(user)
    if not body.confirmed_physical_receipt:
        raise HTTPException(status_code=422, detail="Confirm that the physical item has been received by the office.")
    storage_location = body.storage_location.strip()
    if len(storage_location) < 4:
        raise HTTPException(status_code=422, detail="Record the actual campus room, cabinet, shelf or other storage location.")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row(conn, "reports", "id", report_id)
        row = read_report(conn, report_id)
        if row["report_type"] != "found" or row["status"] != "awaiting_intake":
            raise HTTPException(status_code=409, detail="Only found-item reports awaiting intake can be accepted.")
        if row["submission_channel"] == "public":
            verified_roll = (body.verified_roll_number or "").strip().upper()
            if not body.identity_verified_in_person or verified_roll != (row["roll_number"] or "").strip().upper():
                raise HTTPException(status_code=422, detail="Physically verify the Found reporter's college ID and matching roll number before intake.")
        level = effective_level(row["category"], body.value_band, body.sensitivity_level)
        detail_length = len((body.private_detail or "").strip())
        minimum_detail = 8 if level >= 3 else (6 if level >= 2 else 0)
        if detail_length < minimum_detail:
            raise HTTPException(status_code=422, detail="For this risk level, record a private identifying detail or the approved verification method.")
        year = datetime.now().year
        prefix = "LL-CVR-" + str(year) + "-"
        latest = conn.execute("SELECT tag_id FROM reports WHERE tag_id LIKE ? ESCAPE '!' ORDER BY tag_id DESC LIMIT 1", (prefix + "%",)).fetchone()
        number = int(latest["tag_id"].rsplit("-", 1)[1]) + 1 if latest else 1
        tag_id = prefix + str(number).zfill(6)
        conn.execute(
            """UPDATE reports SET status='available', tag_id=?, storage_location=?, private_detail=?, value_band=?,
               sensitivity_level=?, verification_level=?, updated_at=? WHERE id=?""",
            (tag_id, storage_location, (body.private_detail or "").strip() or None, body.value_band,
             body.sensitivity_level, level, now_iso(), report_id),
        )
        audit(conn, user["id"], "found_item_received_tagged_and_stored", "report", report_id,
              {"tag_id": tag_id, "storage_location": storage_location, "verification_level": "L" + str(level)})
        notify_user(
            conn, row["created_by"], "found-intake:" + report_id,
            "Found item received and stored",
            "Campus office confirmed physical receipt and storage of the item. It is now available for matching.",
            "report", report_id,
        )
        reporter = conn.execute("SELECT role FROM users WHERE id=?", (row["created_by"],)).fetchone()
        if reporter and reporter["role"] == "student":
            award_points(
                conn, row["created_by"], POINT_RULES["verified_intake"],
                "verified-intake:" + report_id,
                "Your found-item report was physically received and verified by the campus office",
                report_id, user["id"]
            )
        notify_possible_matches(conn, read_report(conn, report_id))
        updated = read_report(conn, report_id)
    return {"report": serialise_report(updated, internal=True), "message": "Physical receipt recorded, tag assigned and campus storage location saved."}


@router.post("/api/reports/{report_id}/storage")
async def update_storage_location(
    report_id: str,
    body: StorageLocationBody,
    user: dict[str, Any] = Depends(authenticated_user),
):
    require_office(user)
    storage_location = body.storage_location.strip()
    if len(storage_location) < 4:
        raise HTTPException(status_code=422, detail="Record the actual campus room, cabinet, shelf or other storage location.")
    with connect_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        lock_row(conn, "reports", "id", report_id)
        report = read_report(conn, report_id)
        if report["report_type"] != "found" or not report["tag_id"]:
            raise HTTPException(status_code=409, detail="Only physically received and tagged found items can have a storage location.")
        if report["status"] not in {"available", "claim_approved"}:
            raise HTTPException(status_code=409, detail="Storage location can only be changed while the item is in campus custody.")
        previous_location = report["storage_location"]
        conn.execute("UPDATE reports SET storage_location=?, updated_at=? WHERE id=?",
                     (storage_location, now_iso(), report_id))
        audit(conn, user["id"], "storage_location_updated", "report", report_id,
              {"tag_id": report["tag_id"], "previous_location": previous_location,
               "new_location": storage_location, "note": (body.note or "").strip() or None})
        updated = read_report(conn, report_id)
    return {"report": serialise_report(updated, internal=True), "message": "Campus storage location updated."}
