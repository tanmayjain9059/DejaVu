# Public Student Backend Contract

This document describes the implemented public-student backend on the
`feat/lostlink-public-home-mascot` branch. It does not claim that the frontend
has been migrated to these routes.

## Identity and access model

- Students do not need an account, email, password, or session.
- A mandatory CVR roll number is stored as the attribution key on every public
  report and claim. It is normalized to uppercase.
- Roll number is not authentication. It must never be used by itself to read,
  edit, close, or aggregate private student records.
- Every report and claim receives an independent high-entropy tracking credential.
  Only its SHA-256 digest is stored. The raw credential is returned once at creation.
- The public receipt packages the credential into a private tracking link. The
  student opens or pastes that link; the interface does not ask them to type a
  separate tracking-secret value. The credential unlocks only its own report
  or claim, even when records share a roll number.
- Office staff continue to authenticate through the existing office session.
  Student credentials are rejected by `POST /api/login`.

## Public endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/public/reports` | Submit a lost or found report; requires roll number |
| GET | `/api/public/found` | Browse only found items physically received and released by office |
| GET | `/api/public/track/{reference}?roll_number=...` | Read one report/claim using its tracking secret header |
| POST | `/api/public/cases/{reference}/close` | Close an open lost report or withdraw a found report before intake |
| POST | `/api/public/found/{case_id}/claims` | Submit a claim against an available found item |
| POST | `/api/public/claims/{reference}/evidence` | Add evidence when office requests more evidence |

The browser extracts the credential from the private receipt link's URL fragment
and sends it in the `X-LostLink-Tracking-Secret` header. The reference and
matching roll number are also required. A wrong reference, roll-number mismatch,
or wrong credential returns a generic not-found response. The fragment is not
sent in the HTTP request URL.

### Report submission

`POST /api/public/reports` accepts `report_type`, `roll_number`, `title`,
`description`, `category`, and optional item/location characteristics.
Lost reports start as `open`. Found reports start as `awaiting_intake` and
are excluded from public browsing until office intake is confirmed.

The response contains a public reference and one-time tracking credential.
The frontend turns it into a private receipt link and never renders a separate
tracking-secret input. Do not log the raw credential or store it in analytics.

### Claims

Claims require roll number, evidence text, and evidence-type declarations.
A found-item reporter cannot claim their own report. A competing active claim
places all competing claims into `disputed` and the item into `claim_hold`.
Student-submitted evidence declarations are not treated as proof of identity.

## Office-only endpoints

All routes below require an authenticated office role:

- `GET /api/public/office/intake-queue`
- `GET /api/public/office/roll/{roll_number}/cases`
- `GET /api/public/office/cases/{case_id}`
- `POST /api/public/office/{case_id}/intake`
- `GET /api/public/office/claims`
- `POST /api/public/office/claims/{claim_id}/decision`
- `POST /api/public/office/claims/{claim_id}/handover`

Intake requires explicit physical-receipt confirmation, a staff-assigned Tag ID,
and private custody location. Public serializers never return Tag ID, storage
location, private intake notes, or roll number. Claim approval requires an
explicit staff identity-verification flag and category-level verification
checks. Handover separately requires staff confirmation of claimant identity,
physical handover, and the matching Tag ID.

## Abuse controls

Anonymous report and claim creation have database-backed per-IP rate limits.
Only a one-way IP hash is stored. Cross-origin mutation protection and the
application's existing security headers remain in force.

## Schema and migration safety

The public workflow uses additive, independently versioned tables:
`public_cases`, `public_claims`, `public_case_events`, and
`public_rate_limits`. Existing account-linked reports, claims, audit records,
and office user IDs are not rewritten or deleted. This avoids destructive
conversion of historical records while the new public workflow is introduced.

## Remaining integration work before production

- Migrate the public home, report forms, found-item browser, claim UI, and
  receipt/tracking screens to these routes; remove the mock student preview.
- Add private image upload and evidence-image handling to the public token
  model, using private Supabase Storage and signed access.
- Integrate notifications and activity/reward accounting with roll-attributed
  cases without exposing roll numbers or private records.
- Add institution-approved roll-number validation if CVR supplies a secure
  roster/verification source. Current validation checks only basic syntax and
  does not prove enrolment.
- Add CAPTCHA/bot controls, operational rate-limit tuning, monitoring, and
  retention policies before public launch.
- Execute the complete SQLite and PostgreSQL test suites and perform a
  security review of public API abuse, Supabase policies, and file access.

The current implementation is a backend foundation, not yet a production-ready
public launch. The frontend still contains legacy account-oriented workflows.
