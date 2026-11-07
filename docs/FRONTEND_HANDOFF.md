# LostLink Frontend Handoff

Audience: frontend engineer implementing the student and campus-office experience against the existing FastAPI backend.

Repository: https://github.com/tanmayjain9059/DejaVu  
Backend baseline: `main` (verify current default branch before implementation).  
Core rule: **AI matching is a discovery aid, never proof of ownership.** Only authorised office staff can approve claims and record physical handover.

## 1. Product summary

LostLink is a campus lost-and-found workflow, not a public classifieds board.

- Students submit lost/found reports, browse office-verified found inventory, review possible matches, and submit/track ownership claims.
- Office staff accept physical custody, assign a physical LostLink Tag ID, record actual storage, review claims/evidence and record verified handover.
- Notifications and contribution points communicate verified workflow events.
- Sensitive categories and claim evidence require strict access control.

A found report is **not** visible in student browse until staff confirm physical receipt and storage. An approved claim is **not** a completed return; physical handover is a separate office action.

## 2. Backend and integration constraints

- Backend: Python + FastAPI. Routes: `app/api/routes/auth.py`, `reports.py`, `claims.py`, `engagement.py`.
- Existing UI: static HTML/CSS/vanilla JS in `app/static/`. A new UI may replace it, but preserve API semantics.
- API prefix: `/api`. Interactive schema: `/docs`; OpenAPI JSON: `/openapi.json` when running locally.
- Authentication is a **server-side session cookie, not JWT**. Do not store session IDs, passwords or invented bearer tokens in localStorage.
- Same-origin deployment is required by the current security model: cookie SameSite=Strict and unsafe API requests enforce same-origin Origin/Referer. Build separately if desired, but serve the SPA behind the same origin (reverse proxy or FastAPI static mount). A different frontend domain requires deliberate backend CORS/cookie/CSRF design changes.
- Fetch requests should use `credentials: "same-origin"`; JSON requests set Content-Type; FormData requests must not manually set Content-Type.
- Main's current report listing is capped at 250 and is not cursor-paginated. Do not assume pagination until that branch is integrated and tested.
- Demo accounts only exist with `DEMO_MODE=true`; never expose demo credentials publicly.

## 3. Roles and navigation

### Student
Browse found inventory; create lost/found reports; view My Reports and matches; submit and track claims; add requested evidence or make one review request after rejection; view notifications, activity, certificates and leaderboard.

### Office
Dashboard; found-item intake queue; physical receipt and Tag ID assignment; inventory and storage updates; claims queue and private evidence review; approve/reject/request evidence/mark disputed; approved-for-collection queue and physical handover; notifications and AI diagnostics.

The backend derives role from the session. Hiding a button is not authorisation; handle 401/403/404 responses.

## 4. End-to-end journeys

### Lost report
1. Submit a `lost` report.
2. Optionally upload a photo.
3. Load possible matches for the report.
4. Display candidate item, strength and reasons, with a clear explanation that suggestions are not proof.
5. Refresh after office intake/new notifications.

### Found report
1. Submit a `found` report and optionally upload photo.
2. Explain it is awaiting physical intake and is not searchable yet.
3. It can be withdrawn only before intake.
4. Office confirms physical receipt, records storage and assigns Tag ID.
5. Item becomes available to student browse and matching.

### Claim
1. Open an available found item.
2. Submit private explanation (minimum 20 chars), one or more evidence types, optionally link own open lost report.
3. Optionally upload one private evidence image.
4. Track state and reviewer feedback in My Claims.
5. Add more text evidence when requested; rejected claims may receive one review request.
6. Never expose claim evidence to other students.

### Office review and return
1. Review claims; competing claims may be marked disputed.
2. Inspect private evidence and verify identity/records.
3. Choose approve, reject, request more evidence or mark disputed.
4. Approval moves claim to `approved_for_collection`, not returned.
5. At physical counter, check exact Tag ID and claimant identity; record actual handover.
6. Backend marks claim/report returned and emits audit, notifications and eligible reward events.

## 5. API contract

All paths are same-origin. The running `/docs` and `/openapi.json` are the final schema authority.

### Session/config

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/config` | Categories, sample location directory, demo flag, points and feature flags |
| POST | `/api/login` | Body `{email,password}`; returns `{user}` and sets session cookie |
| POST | `/api/logout` | Clears session |
| GET | `/api/me` | Current authenticated user: `{user}` |

Call `GET /api/me` at startup. A 401 means show login. Do not let a client-side role selector grant access.

### Reports/matching

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/reports` | Filters: `report_type, category, block, room, q, date_from, date_to, status, mine` |
| POST | `/api/reports` | Create lost/found report |
| POST | `/api/reports/category-suggestion` | Advisory AI category suggestion |
| POST | `/api/reports/{id}/image` | Multipart image upload, max 5 MB |
| GET | `/api/reports/{id}/image` | Authenticated image; student images watermarked; sensitive category images restricted |
| POST | `/api/reports/{id}/enrichment` | Optional image caption/keyword enrichment; feature may be disabled |
| GET | `/api/reports/{id}/matches` | Matches for owner's open lost report |
| POST | `/api/reports/{id}/close` | Owner closes eligible lost report or withdraws found report awaiting intake |
| POST | `/api/reports/{id}/intake` | Office confirms receipt, storage and Tag ID assignment |
| POST | `/api/reports/{id}/storage` | Office updates storage location |
| GET | `/api/office/ai-status` | Office-only AI model diagnostics |

Report creation fields:
- Required: `report_type` (`lost`/`found`), `title` (4–100 chars), `description` (10–1200 chars), `category`, and at least one of `location_block` or `location_area`.
- Optional: `brand`, `primary_color`, `visible_features`, `occurred_at` (ISO date/time), `location_block`, `location_floor`, `location_room`, `location_area`.
- Category keys: `stationery`, `clothing`, `bags_wallets`, `accessories`, `electronics`, `identity_documents`, `keys_access`, `cash_jewellery`, `sports_instruments`, `other`.

Category suggestion accepts the report text fields and returns `{suggestion: ...}`. It is advisory; student chooses the final category.

Close body: `{reason, note?}`; reason is `recovered_elsewhere`, `no_longer_searching`, `duplicate`, or `found_report_withdrawn`. The last is only for a found report awaiting intake.

Intake body:
`{confirmed_physical_receipt:true, storage_location:"Block A / Office / Cabinet 2", private_detail:"owner-only verification detail", value_band:"low|medium|high|unknown", sensitivity_level:1}`.
Backend generates Tag ID. Never invent it in the client. Never render private_detail to students.

Storage body: `{storage_location:"Block A / Office / Shelf 3", note?}`.

### Claims/handover

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/claims` | Student's own claims or office review queue |
| POST | `/api/claims` | Student submits claim |
| POST | `/api/claims/{id}/evidence` | Add requested text evidence |
| POST | `/api/claims/{id}/evidence-image` | Attach private evidence image (multipart, max 5 MB; one image) |
| GET | `/api/claims/{id}/evidence-image` | Claimant/office retrieves watermarked private image |
| POST | `/api/claims/{id}/dispute` | One review request for a rejected claim |
| POST | `/api/claims/{id}/decision` | Office decision |
| POST | `/api/claims/{id}/handover` | Office records physical return |

Claim body:
`{report_id:"found-id", lost_report_id:"optional-own-open-lost-id", evidence:"private owner explanation, at least 20 chars", evidence_types:["distinctive_features"]}`.
Allowed unique evidence types (1–6): `distinctive_features`, `purchase_or_receipt`, `packaging_or_accessory`, `timeline_and_location`, `device_or_account_context`, `other`.

Additional evidence body: `{evidence:"updated explanation, at least 20 chars"}`. Review request body: `{reason:"why decision should be reviewed, at least 20 chars"}`.

Office decision body:
`{action:"approve|reject|request_more_evidence|mark_disputed", note?, verification_checks:[]}`.
Allowed checks: `distinctive_features`, `date_location`, `physical_inspection`, `supporting_evidence`, `owner_specific_detail`, `claimant_identity`, `authorised_record`. Approval requires claimant_identity and a verification-level-dependent minimum; level 4 also requires authorised_record. Let API validation drive errors.

Handover body:
`{confirmed_physical_handover:true, claimant_identity_checked:true, tag_id:"exact-physical-tag", note?}`.
Only approved_for_collection claims can be handed over; entered tag must exactly match backend record.

### Notifications/rewards/office

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/notifications` | Notifications and unread count |
| POST | `/api/notifications/{id}/read` | Mark one read |
| POST | `/api/notifications/read-all` | Mark all read |
| GET | `/api/activity/me` | Student points, ledger, certificates and milestones |
| GET | `/api/leaderboard` | Student contribution leaderboard |
| GET | `/api/certificates/{id}/download` | Authenticated PDF download |
| GET | `/api/office/summary` | Office queue counters |

## 6. State semantics

Report statuses include:
- `open`: lost report actively searching.
- `awaiting_intake`: found report awaiting office physical custody.
- `available`: found item received, tagged and searchable.
- `claim_approved`: item awaiting physical handover.
- `returned`: physical handover completed.
- `closed`: lost search closed.
- `cancelled`: found report withdrawn before intake.

Claim statuses include `pending`, `disputed`, `needs_more_evidence`, `approved_for_collection`, `rejected`, `returned`.

Render friendly labels but retain exact API values. Never present disputed items as collectable. Never equate approved_for_collection with returned.

Match response: `{matches:[{report,strength,reasons,...}],note}`. Strength is a ranking signal, not probability or ownership confidence. Reasons are discovery explanations only.

Report list response: `{reports:[...]}`. Student browse is restricted to available found items; `mine=true` gets the user's own records. Office sees broader records subject to filters.

## 7. Suggested screens

### Shared shell
Responsive layout, brand, authenticated profile, server-derived role, sign out, notification badge, global loading/error/empty states.

### Student
- Browse: keyword/category/block/room/date filters, item cards, details and claim action only for available items.
- New report: lost/found chooser, guided fields, photo preview/upload, optional AI category suggestion and explicit user confirmation.
- My Reports: status, photo, allowed close/withdraw actions; matches for open lost reports.
- My Claims: state timeline, evidence types, private evidence, add-evidence/review-request controls according to status.
- Notifications.
- Activity: points, ledger, milestone progress, certificates and leaderboard.

### Office
- Dashboard from `/api/office/summary`.
- Intake queue for awaiting_intake reports; review image/details; record receipt/storage/private detail.
- Inventory: Tag ID and storage location; update location.
- Claim review: claimant identity, private evidence, linked lost report, verification checklist, reviewer note and decision controls.
- Handover: approved_for_collection only; exact Tag ID, identity and physical confirmation.
- AI diagnostics from `/api/office/ai-status`.

## 8. API client pattern and errors

Use one typed API client:

```ts
async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init, headers, credentials: "same-origin",
  });
  const isJson = (response.headers.get("content-type") || "").includes("application/json");
  const payload = isJson ? await response.json() : await response.blob();
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && "detail" in payload
      ? String(payload.detail) : `Request failed (${response.status})`;
    throw Object.assign(new Error(detail), { status: response.status, payload });
  }
  return payload as T;
}
```

Handle: 401 session expired; 403 role/permission denied; 404 record unavailable to this user; 409 workflow conflict (show backend message and refresh); 413 upload too large; 422 validation; 429 login throttling (respect Retry-After); 5xx/network errors. Do not auto-retry non-idempotent report/claim/handover submissions.

For private images/PDFs, use authenticated fetch and Blob URLs; revoke URLs on unmount. Never cache private responses in service workers/CDNs.

## 9. Privacy and accessibility

- Never show `private_detail`, claimant evidence, claimant email, reviewer notes or internal AI scores to students.
- Never expose sensitive-category images (identity documents/access keys) to students.
- Never imply AI determines ownership.
- Do not place private evidence in localStorage, analytics, logs or telemetry.
- Require explicit confirmation for office decisions and handover.
- Tag ID is an operational identifier, not a public item identifier.
- Use semantic headings, labels, keyboard navigation, visible focus, announced errors and adequate contrast.
- For workflow transitions, wait for server success and refresh authoritative state.

## 10. Delivery sequence

1. API client, session restoration, login/logout, role-aware shell.
2. Student browse, report submission and image upload.
3. My Reports and match explanations.
4. Claim submission, My Claims and private evidence.
5. Office dashboard, intake and inventory.
6. Office claim review and physical handover.
7. Notifications, points, certificates and leaderboard.
8. Responsive/mobile polish, accessibility and E2E coverage.

## 11. Acceptance scenarios

1. Unauthenticated user sees login; valid login survives refresh; logout clears access.
2. Student creates lost report; it appears in My Reports and matches load.
3. Student found report is hidden from browse while awaiting intake.
4. Office accepts item; Tag ID/storage saved; item becomes searchable.
5. Student submits claim; another student cannot access private evidence.
6. Office requests more evidence; claimant adds it; office sees update.
7. Approval moves claim to approved_for_collection, not returned.
8. Incorrect Tag ID fails; correct Tag ID plus identity/physical confirmation completes handover.
9. Competing claims are disputed and cannot be approved until resolved.
10. Notifications update; points appear only after backend-awarded events.
11. Sensitive photos and office-only details remain inaccessible to students.
12. Primary flows work on mobile widths and with keyboard-only navigation.

## 12. Known integration gaps (do not assume these are implemented on main)

- Current main report listing caps at 250 rows; matching candidates cap at 500. Full-corpus matching and cursor pagination are in a separate diverged branch and must be integrated/tested before relying on them.
- Current location directory is sample data (Block A/B/C, Library, Cafeteria). Replace with verified campus directory.
- Invite-based office onboarding and object-storage changes are not assumed on main until integrated and validated.
- College-wide launch still requires production database/storage configuration, identity/onboarding policy, load tests, monitoring, backup/restore rehearsal, retention policy and manually adjudicated campus matching evaluation.

## 13. Local backend setup

```bash
git clone https://github.com/tanmayjain9059/DejaVu.git
cd DejaVu
git switch main
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set the generated value as `SESSION_SECRET` in `.env` (32+ chars). For a local-only demo:

```dotenv
DEMO_MODE=true
USE_SEMANTIC_MODEL=false
USE_CLIP_MODEL=false
USE_IMAGE_ENRICHMENT=false
```

Run:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the API schema and `http://127.0.0.1:8000` for the current UI. Use demo credentials shown by the local login screen only.

---

**Frontend principle:** build the client experience, but keep the backend as source of truth for identity, permissions, report visibility, claim state, verification policy, Tag IDs, handover and reward awards.
