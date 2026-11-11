# Production deployment checklist

## Before deployment

- [ ] Confirm institution approval for public roll-number attribution and in-person identity checks.
- [ ] Configure Supabase PostgreSQL and verify additive migrations on a staging copy.
- [ ] Configure office-only Supabase Auth with an exact `OFFICE_USER_EMAILS` allowlist.
- [ ] Confirm no student signup, password login, Google login or OTP flow is enabled.
- [ ] Configure the Vercel origin in `FRONTEND_ORIGINS` and verify CORS preflight for `X-LostLink-Tracking-Secret`.
- [ ] Configure HTTPS, canonical host allowlist, secure session settings and unique secrets.
- [ ] Configure private object storage and verify authenticated-only access.
- [ ] Back up the database and private uploads before migration or release.

## End-to-end release gate

- [ ] Anonymous Lost report submission writes to canonical `reports`.
- [ ] Anonymous Found report submission writes to canonical `reports` and remains hidden until office intake.
- [ ] Office intake checks the physical reporter ID and matching roll number, records custody and assigns a Tag ID.
- [ ] Public Found browse returns only available items and never exposes roll numbers, Tag IDs or storage locations.
- [ ] Public claims write to canonical `claims` and appear in the existing office review queue.
- [ ] Competing claims are disputed and cannot bypass office verification.
- [ ] Claim approval checks the claimant's physical ID, matching roll number and category-level verification checklist.
- [ ] Handover checks claimant identity and the recorded Tag ID before marking the item returned.
- [ ] Lost report matching uses the same bounded retrieval and AI ranking path as the authenticated workflow.
- [ ] Notifications and rewards are linked to the correct canonical case.
- [ ] A tracking secret cannot access any other report or claim, even when the roll number is the same.
- [ ] Student authentication is rejected by both local and Supabase providers.
- [ ] Office authentication works only for exact allowlisted staff emails.
- [ ] Public image/evidence upload remains disabled until token-scoped private-storage access is implemented.

## Operations

- [ ] Run SQLite unit and integration tests.
- [ ] Run PostgreSQL end-to-end public workflow tests.
- [ ] Run frontend selector/navigation and JavaScript syntax checks.
- [ ] Verify migration 10 and legacy public-record migration on a staging copy.
- [ ] Review public API rate limits, abuse monitoring, CAPTCHA and alerting.
- [ ] Verify retention, deletion, backup and restore procedures.
- [ ] Complete security review and college approval before broad launch.
