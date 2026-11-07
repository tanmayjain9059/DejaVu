# LostLink — No-Login Student Workflow (Pilot Decision)

## Decision

For the college pilot, students do not create accounts and do not sign in. A student supplies their college roll number when submitting each lost-item or found-item report. The office manually verifies the student and the report before treating the submission as trusted.

Office access remains authenticated and role-restricted. Removing student login must not make the office console, claim evidence, internal notes, storage locations, or handover actions public.

This document records the approved product direction. It is an implementation specification, not a statement that the code has already been changed.

## Student workflow

1. A visitor opens LostLink and can browse only found items that office staff have physically received and approved for discovery.
2. The visitor chooses **I lost something** or **I found something**.
3. The report form requires:
   - College roll number in the approved CVR format.
   - Item title and description.
   - Category.
   - Approximate date/time, when known.
   - Campus block/area.
   - Optional safe-to-share characteristics and photograph.
4. The API normalises the roll number (trim whitespace and uppercase) and validates its syntax. Syntax validation is not proof that the roll number is real or belongs to the submitter.
5. The API stores the report against a non-login student identity keyed by the roll number. No student password, email account, Google OAuth account, or self-assigned role is created.
6. The student receives a public report reference for support and can use the roll number to find their own submission summaries.
7. The office checks the roll number against the college record and verifies the report as needed. A report is not considered proof of ownership merely because it contains a valid-looking roll number.

## Roll-number tracking: privacy boundary

The pilot decision is to use the roll number alone for student tracking. This is convenient but is **not authentication**: roll numbers can be observed, guessed, or enumerated.

Therefore the roll-number tracking endpoint must return only a minimal status view, such as report reference, report type, item title, submission date, and current workflow status. It must never return:
- Claim evidence or evidence-image URLs.
- Student phone numbers, email addresses, or other contact details.
- Internal officer notes, hidden item characteristics, custody location, or physical Tag ID.
- Other students' reports or claims.
- Private report-image URLs for lost reports.

Tracking requests must be rate-limited by source IP and normalised roll number, use generic not-found responses, and avoid revealing whether a roll number is registered. The UI must clearly state that roll-number tracking is a convenience lookup, not a secure private account. If the college later requires confidential self-service claim history, add a second factor (for example, a one-time code delivered to a verified institutional channel) rather than treating the roll number as a secret.

## Claims and physical recovery

- A student can submit a claim using the roll number associated with their lost report, or provide the roll number with the claim when no lost report is linked.
- Claim evidence is stored privately and is visible to authorised office staff only in the no-login student mode.
- Student-facing tracking may show claim status and next action, but must not reveal private evidence, reviewer notes, competing claimant information, or evidence images.
- Office staff manually verify the claimant's identity against the college ID/records and inspect ownership evidence.
- Claim approval does not mean an item has been returned.
- Physical handover still requires the exact LostLink Tag ID, an in-person identity check, and an officer's explicit handover confirmation.

## Office access

- Keep the office console behind authenticated office access.
- Only explicitly provisioned office identities can access intake, inventory, private claims, internal verification data, storage locations, reports of all students, audit records, and handover actions.
- Never infer the office role from a roll number, request body, query parameter, or student-controlled metadata.
- Demo role switching and demo credentials must remain development-only and must not be enabled in a public deployment.

## Data and API implementation plan

### Data model

- Add a nullable, unique `roll_number` column to the existing `users` table.
- Create or resolve a student record by the normalised roll number. These are internal attribution records, not login accounts.
- Preserve the existing `reports.created_by`, `claims.claimant_id`, reward ledger, audit, and handover foreign-key relationships so the existing workflow does not need to be rewritten.
- Keep existing office users and their authentication credentials/identity mappings intact.
- Do not backfill a roll number from an email address or guess it from old demo data.

### API changes

- Add a public student report submission path that requires a syntactically valid `roll_number` in every report payload.
- Add a rate-limited roll-number tracking endpoint that returns only the minimal status projection described above.
- Require the same roll-number identity for student-owned report edits, closures, image uploads, claims, and claim follow-up actions. Do not accept a user ID or role from the browser.
- Keep office endpoints behind the existing office authentication dependency.
- Keep public browsing limited to approved found-item listings.
- Add explicit authorization tests for cross-roll-number access and private claim evidence.

### Frontend changes

- Remove student email/password login and student sign-up from the public entry flow.
- Make Browse, Report Lost, Report Found, and Track Submission available without a student account.
- Require a roll-number field on both lost and found report forms, with inline format guidance and normalisation.
- Add a roll-number tracking form. Display only the minimal status projection; do not render private claim evidence or internal fields.
- Keep a separate, clearly labelled officer sign-in entry point.
- Keep existing matching, office intake, Tag ID, claim decision, and handover workflows unless a security test requires a specific student-facing restriction.

## Validation and acceptance criteria

1. A student can submit a lost report without an email, password, or student login.
2. A student can submit a found report without an email, password, or student login.
3. Both report types reject missing or malformed roll numbers.
4. The same normalised roll number maps to the same internal student attribution record.
5. Roll-number tracking returns only that roll number's minimal report/claim status projection.
6. Tracking never exposes evidence, private notes, contact details, Tag IDs, or storage locations.
7. A different roll number cannot edit or close another student's report or upload an image to it.
8. Student requests cannot access office queues, private claim evidence, internal storage data, or handover actions.
9. An unauthenticated visitor cannot access the office console.
10. Existing report matching, office intake, claim review, Tag ID validation, audit and physical handover tests continue to pass.
11. Rate limits and generic not-found responses prevent easy roll-number enumeration.
12. Public deployment configuration disables demo accounts and demo role switching.

## Roll-number format configuration

Do not hard-code a speculative pattern throughout the code. Use one central, configurable validation rule (for example, `ROLL_NUMBER_REGEX`) and confirm the exact accepted CVR format with the college office before launch. The format must match the institution's actual current and legacy roll-number formats.

## Rollout

Implement this on the feature branch `feat/no-login-roll-number-workflow`. Preserve `main` until the backend, frontend, privacy controls, migration, and tests are complete. Do not enable the new student mode on a public deployment until the acceptance criteria pass.
