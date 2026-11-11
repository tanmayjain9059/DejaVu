# LostLink issue-register remediation status

Branch: `feat/lostlink-unified-public-workflow`
Status: remediation merged into the deployment branch. Render backend is live on commit `08780bd33a46380541bfc0ae8229d1eec5b3e41e`; the app starts successfully and the service returned HTTP 200 after deployment. Browser end-to-end smoke audit is being rerun against the updated private-tracking-link flow.

## Implemented in this branch

| Issue area | Remediation |
|---|---|
| Proxy/IP trust | Use a validated Cloudflare `CF-Connecting-IP` address for public rate limits; never trust caller-supplied `X-Forwarded-For`. Uvicorn no longer trusts every proxy. |
| Demo authentication | Render `DEMO_MODE=false`; local demo login remains fail-closed when Supabase auth is configured. |
| Public roll attribution | Roll number is explicitly attribution, not authentication. Anonymous requests use high-entropy per-case tracking secrets and IP/action rate limits. |
| Browser CSP | Same-origin-only script policy; removed the Supabase browser CDN entirely and replaced it with a small first-party Auth REST client. |
| Public disclosure | Public Lost records hide exact location/time; public Found records redact free text and sensitive identity/access categories. |
| Photo oracle | Anonymous/student upload routes no longer disclose whether a submitted image matches another person's stored image. Office-only duplicate checks remain. |
| Upload concurrency | Object-storage writes happen outside database write locks; the report/claim row is rechecked under a targeted lock before commit. |
| PostgreSQL concurrency | Replaced the global advisory write lock with row-level locks for reports, claims, users and privacy requests, plus per-IP/action and per-roll advisory locks. SQLite retains `BEGIN IMMEDIATE`. |
| Claim limits | Approved-for-collection is included in authenticated active-claim quotas and competing-claim checks. Anonymous public claims cannot safely use a roll-number quota because roll numbers are spoofable. |
| Rewards | Only exact office-confirmed intake and return event keys/amounts can award points. Recipient and acting office role and underlying report/handover are checked. |
| Search | LIKE wildcard characters are escaped; public search uses only non-sensitive category/colour/reference descriptors. |
| AI consent | New reports default to no image-AI consent. Explicit opt-in is required for CLIP image matching and optional captioning; owners can withdraw consent, which clears generated captions and cached image vectors. |
| Model supply chain | Model downloads are disabled by default. Enabling downloads requires a pinned immutable 40-character model revision. Hugging Face telemetry is disabled by default. |
| Privacy rights | Added authenticated data export, verified public-case export, access/correction/erasure request intake, an office review queue, decision audit trail and a public privacy notice. |
| Privacy database security | Privacy request records are RLS-enabled and inaccessible to Supabase browser roles. |
| Startup/migrations | Schema bootstrap is serialised; legacy image fingerprint backfill is bounded; expired rate-limit digests are pruned at startup rather than on each request. |
| References/timeouts | Increased report reference entropy, added bounded API timeouts and cold-start retry messaging, and standardised certificate serial years to UTC. |
| Static frontend | Added checks for duplicate DOM IDs, missing literal JS selectors, third-party scripts, inline handlers, CSP and duplicate public workflow routes. |
| CI/deployment | Added GitHub CI for Python compile, JavaScript syntax and tests, Chromium responsive browser audit, plus a manual Cloudflare Pages build/deploy workflow. |

## Release gates and dependencies

1. **CI execution:** The latest application CI run passed (173 tests, Python compilation and JavaScript syntax). The PostgreSQL integration suite also passed, including public workflow, competing claims, race regressions and SQLite-to-PostgreSQL migration. A Chromium audit is being rerun after updating its retired tracking-field selectors. Vercel still reports a platform build-rate-limit failure (`upgradeToPro=build-rate-limit`), not a source-code test failure.
2. **Cloudflare deployment credentials:** The Pages workflow requires repository secrets `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and repository variable `CLOUDFLARE_PAGES_PROJECT_NAME`. `LOSTLINK_API_ORIGIN` is optional and defaults to the Render API origin.
3. **DPDP retention approval:** No college-approved retention periods or backup-deletion schedule were supplied. The app therefore does not invent retention durations or automatically purge closed cases. An authorised office reviewer must assess erasure requests and document any retention basis. Provider-side Supabase Auth deletion remains an administrator action.
4. **Identity assurance:** The public workflow intentionally has no student login. A roll number is not proof of identity. Campus office staff must verify identity and ownership before physical handover; a spoofable roll number is never used as a security principal.
5. **PostgreSQL integration:** The GitHub PostgreSQL 16 integration suite passed targeted row-lock and advisory-lock workflows, concurrent competing claims, duplicate handover, closure-versus-approval race, uniqueness guards, and the SQLite-to-PostgreSQL migration smoke test. Repeat concurrency tests against the actual Supabase PostgreSQL instance before production sign-off.
6. **Live browser smoke tests:** Render deployment is live, but full interactive browser verification remains pending. Test Lost and Found submission, private tracking, matching refresh, claim evidence, office intake, competing claims, handover, photo-consent withdrawal, privacy export/request and office privacy review.
7. **Frontend origins:** Render has `FRONTEND_ORIGINS`, HTTPS-only sessions, request-origin enforcement and the API host allowlist configured. Confirm the final production Cloudflare response headers and exact origin set after frontend deployment. Render secret values are intentionally not copied into source control.

## Security design notes

- Public tracking secrets are high-entropy, displayed once and stored only as hashes.
- Public request rate limits use the validated Cloudflare edge IP, not arbitrary forwarding headers.
- PostgreSQL pooled connections disable automatic prepared statements to remain compatible with transaction-pooler deployments.
- AI is advisory. No model score establishes ownership or authorises a handover.
- A photo can be stored privately for human office review without consenting to AI photo processing.
- Erasure is not automatically applied to an open ownership dispute or custody record. Office staff must review the case and record the action taken.
