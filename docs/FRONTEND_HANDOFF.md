# Frontend integration handoff

## Access model

LostLink uses a public student workflow. Students do **not** create accounts, sign in, use Google OAuth, or request OTPs.

- A college roll number is collected for attribution and physical office verification. It is not an authentication credential.
- Every submitted report and claim receives its own high-entropy tracking secret. The raw secret is shown once; the database stores only its SHA-256 digest.
- A tracking secret unlocks only the report or claim whose reference it was issued for. It does not unlock every record associated with a roll number.
- Only campus office accounts on the exact `OFFICE_USER_EMAILS` allowlist may authenticate. Supabase Auth is used for those staff accounts only.
- Student sign-in, signup, student demo credentials, and role switching must not be reintroduced in the frontend.

## Public student journey

1. The landing page is the initial view. It remains visible until a user chooses an action.
2. **Report lost** and **Report found** open the shared public report form as a destination view, not an extra section below the landing page.
3. The form requires roll number, item title, category, description, and a campus block or nearby area. Brand, colour, visible features and approximate date are optional.
4. A successful submission displays a public reference and one-time tracking secret. The student must save both.
5. A Lost report starts open and can receive ranked possible-match suggestions.
6. A Found report starts as `awaiting_intake`. It is not publicly searchable until office staff physically receive the item, verify the reporter's college ID, record custody, assign a Tag ID and complete intake.
7. Students can search open Lost reports and Found items whose status is `available`; only Found items can be claimed. A claim requires roll attribution and private evidence text.
8. A student tracks a report or claim with its reference, roll number and matching tracking secret.

## Public API contract

All public routes are under `/api/public`. They do not require a session cookie or Supabase bearer token.

| Method | Route | Purpose |
|---|---|---|
| POST | `/api/public/reports` | Submit a Lost or Found report |
| GET | `/api/public/search` | Search open Lost reports and available Found items | 
| GET | `/api/public/found` | Browse available Found items only |
| GET | `/api/public/track/{reference}?roll_number=...` | Read one token-authorised report or claim |
| GET | `/api/public/reports/{reference}/matches?roll_number=...` | Retrieve ranked matches for one Lost report |
| POST | `/api/public/found/{report_id}/claims` | Submit a claim with private evidence |
| POST | `/api/public/claims/{reference}/evidence` | Add evidence after the office requests it |
| POST | `/api/public/cases/{reference}/close` | Close an eligible Lost report or withdraw a Found report before intake |

Tracking requests send the one-time secret in `X-LostLink-Tracking-Secret`. The backend CORS allow-header list includes this header. Public fetches use `credentials: "omit"`.

A successful report response contains `case.id`, `case.reference`, `case.status`, `tracking_secret`, and a bounded `matches` list for Lost reports. A successful claim response contains `claim.id`, `claim.reference`, `claim.status`, and `tracking_secret`.

## Office workflow integration

Office staff use the existing authenticated dashboard and canonical routes:

- `GET /api/reports` — office queues and inventory.
- `POST /api/reports/{report_id}/intake` — physical Found-item intake.
- `GET /api/claims` — active claims and review queues.
- `POST /api/claims/{claim_id}/decision` — approve, reject, dispute or request evidence.
- `POST /api/claims/{claim_id}/handover` — record the physical return.

For public submissions, office actions must include `identity_verified_in_person` and the physically checked `verified_roll_number`. The backend compares it with the private roll attribution stored on the report or claim. Handover separately verifies claimant identity and the matching Tag ID.

## Privacy and integration invariants

- Public report and found-item serializers never return roll numbers, Tag IDs, private storage locations, private intake notes or staff-only verification details.
- Public search must never filter by or expose roll number.
- Public tracking must check reference + matching roll number + the corresponding tracking-secret digest.
- Do not put raw tracking secrets in logs, analytics, query strings, browser storage or error reports.
- Do not use the roll number alone to read, update, close, claim, or enumerate records.
- Public reports and claims write to the canonical `reports` and `claims` tables. Do not create a second student-only business workflow.
- The canonical matching, notifications, audit, rewards, intake, review and handover services are shared with the public workflow.

## Current frontend limitations

Public image upload and public evidence-image upload are not yet enabled. The public form currently submits text and structured item attributes. Existing report-photo and evidence storage remains private and accessible only through authenticated application routes. Do not add a public image URL until a case-token-scoped signed-access flow is implemented and reviewed.

Before launch, add CAPTCHA/bot controls, institution-approved roll-number validation, public image/evidence handling, retention rules, operational monitoring and a security review.
