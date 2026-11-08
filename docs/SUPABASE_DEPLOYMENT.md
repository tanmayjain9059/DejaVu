# Supabase + Vercel + Render deployment runbook

## Target architecture

- **Frontend:** Vercel static build.
- **API:** FastAPI service on Render.
- **Database:** Supabase PostgreSQL.
- **Authentication:** Supabase Auth for authorised campus office staff only.
- **Uploads:** private Supabase Storage through its S3-compatible endpoint.
- **Students:** no account, password, Google login, OTP, or Supabase identity is required.

The public student workflow is deliberately separate from office authentication. A college roll number is stored as private attribution and used for physical office verification; it is never an authentication credential. Each report and claim receives a separate high-entropy tracking secret. Only its SHA-256 digest is stored.

## 1. Create Supabase resources

1. Create the Supabase project in the intended production region.
2. Copy the project URL and anon/public key for the office sign-in client.
3. Copy the PostgreSQL connection string from the Supabase database settings. Prefer the provider's pooler connection when required by the Render service.
4. Create a private Storage bucket for report photos and claim evidence. Keep public access disabled.
5. Configure the S3-compatible Storage endpoint and access keys. Do not expose the secret access key to Vercel or the browser.

The backend connects to PostgreSQL directly through `DATABASE_URL`. Supabase Data API privileges remain locked down by the repository's migration. The browser must not query `reports`, `claims`, roll-attribution tables, or private storage directly.

## 2. Configure office-only Supabase Auth

Set these Render environment variables:

```env
AUTH_PROVIDER=supabase
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=YOUR_SUPABASE_ANON_KEY
SUPABASE_REQUIRE_CONFIRMED_EMAIL=true
OFFICE_USER_EMAILS=authorised.office@college.edu,another.office@college.edu
ALLOWED_EMAIL_DOMAINS=college.edu
```

Important rules:

- `OFFICE_USER_EMAILS` is the exact email allowlist. A matching domain alone does not grant office access.
- `ALLOWED_EMAIL_DOMAINS` is only a secondary domain restriction. It does not replace the exact office allowlist.
- Create/invite office identities through the Supabase project administration process. Do not expose student signup in the app.
- The frontend uses `signInWithPassword` only for the office login panel.
- The backend checks the exact office allowlist before provisioning or accepting a Supabase identity.
- `GET /api/me` returns an office profile only. Existing student Supabase sessions are rejected and signed out by the frontend.
- Public student report, browse, claim and tracking requests do not send a Supabase bearer token or session cookie.

## 3. Configure the Render API

Required or production-recommended variables:

```env
DATABASE_URL=postgresql://...
AUTH_PROVIDER=supabase
SUPABASE_URL=https://YOUR_PROJECT.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_REQUIRE_CONFIRMED_EMAIL=true
OFFICE_USER_EMAILS=authorised.office@college.edu
ALLOWED_EMAIL_DOMAINS=college.edu
SESSION_SECRET=GENERATE_A_UNIQUE_RANDOM_SECRET_AT_LEAST_32_CHARACTERS
SESSION_HTTPS_ONLY=true
HTTPS_ONLY=true
REQUIRE_REQUEST_ORIGIN=true
ALLOWED_HOSTS=your-api.onrender.com
FRONTEND_ORIGINS=https://your-app.vercel.app
UPLOAD_STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://YOUR_PROJECT.supabase.co/storage/v1/s3
S3_BUCKET=lostlink-private
S3_PREFIX=lostlink-private
S3_REGION=YOUR_STORAGE_REGION
S3_ACCESS_KEY_ID=...
S3_SECRET_ACCESS_KEY=...
```

Use the exact Storage endpoint, region and credentials supplied by Supabase. Keep the bucket private. The application stores opaque upload keys, not public object URLs.

Deploy the API with the repository's Render configuration or the command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

The application applies additive schema migrations at startup. Back up the database before deploying to an existing environment and review migration output. Migration 10 adds roll attribution, tracking hashes, public claim references, rate-limit storage and internal non-login attribution identities. The public workflow also migrates records from the retired parallel public tables into canonical reports and claims without dropping those legacy tables.

## 4. Configure Vercel

Set the Vercel environment variable:

```env
BACKEND_ORIGIN=https://your-api.onrender.com
```

The build emits `deployment-config.js` with the API origin and public Supabase client configuration. The Supabase anon key is not a service-role key. The browser must never receive the Supabase service-role key, database password, S3 secret access key or session secret.

Deploy the static frontend. Copy its exact production origin into Render's `FRONTEND_ORIGINS`. Include preview origins only when they are deliberately approved.

## 5. Cross-origin and token handling

- Public browser requests use `credentials: "omit"`.
- Office API requests use the Supabase access token.
- CORS allows `Authorization`, `Content-Type` and `X-LostLink-Tracking-Secret`.
- State-changing requests from the configured Vercel origin are accepted by the origin middleware; unconfigured origins remain blocked.
- Never send a tracking secret in a URL or persist it in analytics. Use the `X-LostLink-Tracking-Secret` header for tracking and evidence updates.
- Roll number + reference + tracking secret must all match. Roll number alone never authorises access.

## 6. Deployment verification

Before launch, verify:

1. Unauthenticated users can submit Lost and Found reports.
2. Student login/signup does not exist in the public UI and student identities are rejected by both local and Supabase auth.
3. A Lost report enters the canonical reports table and uses the existing matching pipeline.
4. A Found report remains hidden from public search until office staff confirm physical receipt, matching roll number and Tag ID.
5. Public claims appear in the canonical office claims queue.
6. Claim approval requires office review, physical identity verification and the required category-level checks.
7. Physical handover requires claimant ID verification and the matching Tag ID.
8. A tracking secret for one report or claim cannot open another record, even for the same roll number.
9. Public serializers do not expose roll numbers, Tag IDs, private storage locations, private evidence or internal notes.
10. Public requests work from the exact Vercel origin and fail from an unapproved origin.
11. Private uploads are not publicly readable and backup/restore has been tested.
12. SQLite and PostgreSQL integration tests pass.

## 7. Remaining launch gates

The public workflow is a backend/frontend integration baseline, not yet a complete production launch. Public image and evidence-image upload are pending; existing private image routes remain authenticated. Add CAPTCHA/bot controls, validate roll-number syntax with CVR, agree the in-person verification process, establish retention and deletion policies, tune rate limits, monitor abuse, and complete a security review before college-wide launch.
