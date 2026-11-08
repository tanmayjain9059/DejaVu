# Public student workflow contract

## Identity and access

LostLink does not require students to register or sign in. Public students submit reports and claims using their college roll number as private attribution. The roll number is not a password, session token, or authentication factor.

Every report and claim receives a separate random tracking secret. The raw secret is returned once; the database stores only a SHA-256 digest. Tracking requires the exact public reference, matching roll number and matching secret. One case's secret cannot unlock another case, even when both cases share a roll number.

Only campus office staff authenticate. Supabase Auth is restricted to the exact `OFFICE_USER_EMAILS` allowlist. Local password login also rejects student-role records. Legacy student rows remain only as historical/internal attribution principals and are not login identities.

## Canonical data model

Public records are written into the same tables used by the rest of LostLink:

- `reports`: `roll_number`, `tracking_hash` and `submission_channel='public'` identify a public report.
- `claims`: `claimant_roll_number`, `tracking_hash`, `public_ref` and `submission_channel='public'` identify a public claim.
- `public_roll_identities`: maps a roll number to a randomly named, non-login internal student principal. No credentials are issued to the student.
- `public_rate_limits`: stores a one-way IP hash, action and timestamp for anonymous write limits.

The additive schema migration is version 10. Existing account-based rows default to `submission_channel='account'`. The old `public_cases` and `public_claims` tables are retained only for backward-compatible migration; new requests do not write to them. Startup migration copies legacy rows into canonical `reports` and `claims` without dropping the source tables.

## Report lifecycle

### Lost

- Starts as `open`.
- Uses the same two-tier candidate retrieval and matching ranker as the existing workflow.
- Possible matches are advisory; they do not establish ownership.
- Case-scoped tracking exposes only that report's updates and any points recorded against that report.

### Found

- Starts as `awaiting_intake`.
- Is excluded from public browse until office staff confirm physical receipt.
- Intake requires the staff member to verify the reporter's college ID and enter the matching roll number.
- Staff record private custody location and details, assign a Tag ID, and complete intake.
- Only `available` found items appear in public browse.

## Claims and physical return

- A public claim requires roll attribution, private evidence text and valid evidence-type declarations.
- The claim is stored in canonical `claims` and appears in the existing office review queue.
- Competing active claims are moved to `disputed`.
- Office approval requires the existing category-level verification checklist plus an in-person identity flag and the matching claimant roll number.
- Handover separately requires claimant identity confirmation, the matching roll number and the recorded Tag ID.
- Existing audit, notification and reward services are reused.

## Public API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/public/reports` | Create a Lost or Found report |
| GET | `/api/public/search` | Search open Lost reports and available Found items |\n| GET | `/api/public/found` | Browse available Found items only |
| GET | `/api/public/track/{reference}` | Track one report or claim |
| GET | `/api/public/reports/{reference}/matches` | Retrieve ranked matches for one Lost report |
| POST | `/api/public/found/{report_id}/claims` | Submit a claim |
| POST | `/api/public/claims/{reference}/evidence` | Add requested evidence |
| POST | `/api/public/cases/{reference}/close` | Close or withdraw an eligible report |

Tracking and evidence-update requests require `X-LostLink-Tracking-Secret` and the matching `roll_number` query parameter. Public requests do not use cookies or Supabase bearer tokens.

## Privacy invariants

Public report and found-item responses do not include roll numbers, Tag IDs, private storage locations, private intake notes or staff-only verification fields. Public search never searches by roll number. Raw tracking secrets must never be logged or included in URLs, analytics or telemetry.

The public API currently returns no public image URL. This is intentional: public image and evidence-image upload/access must be implemented with token-scoped signed access to the private storage bucket before enabling those controls.

## Abuse controls and launch gates

Anonymous report and claim writes have database-backed per-IP rate limits. Production also requires CAPTCHA/bot controls, rate-limit tuning, monitoring, retention rules, approved roll-number syntax/roster validation, private image support and a security review. A syntactically valid roll number does not prove enrolment.
