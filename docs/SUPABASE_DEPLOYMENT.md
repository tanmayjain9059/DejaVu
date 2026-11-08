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
FRONTEND_ORIGINS=https://deja-vu-eta.vercel.app
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
- CORS allows `Authorization`, `Content-Type`, `X-LostLink-Tracking-Secret`, and `X-LostLink-Roll-Number`.
- Public tracking sends the roll number in a request header, never in the URL, to avoid leaking it into proxy/access logs.
- State-changing requests from the configured Vercel origin are accepted by the origin middleware; unconfigured origins remain blocked.
- Never send a tracking secret in a URL or persist it in analytics. Use the `X-LostLink-Tracking-Secret` header for tracking and evidence updates.
- Roll number + reference + tracking secret must all match. Roll number alone never authorises access.

## 6. Verify that Vercel submissions reach Supabase PostgreSQL

### A. Configure the API service (Render)

The static Vercel frontend does **not** write to PostgreSQL directly. The FastAPI service on Render owns the database connection. In Render → LostLink API → Environment, set:

- `DATABASE_URL`: Supabase → Project Settings → Database → Connection string → URI. Use the Supabase **Session pooler** URI if Render's outbound IPv4/network setup requires it; use the correct database password and keep the full URI private.
- `SUPABASE_URL` and `SUPABASE_ANON_KEY`: the project URL and publishable/anon key used by the office authentication client. These are not a substitute for `DATABASE_URL`.
- `FRONTEND_ORIGINS`: the exact deployed Vercel origin, e.g. `https://deja-vu-eta.vercel.app` (no trailing slash).
- The other required variables in `render.yaml`, including office allowlist and private Storage credentials.

Do not paste `DATABASE_URL`, database password, service-role key or Storage secret into Vercel frontend variables or browser code.

### B. Configure Vercel

In Vercel → Project → Settings → Environment Variables, add:

```env
BACKEND_ORIGIN=https://lostlink-api.onrender.com
```

Replace the value with the actual Render API origin. Apply it to the environment you are testing (Preview and/or Production), save, then redeploy. The build now fails if this variable is absent or malformed instead of publishing a frontend that can never reach the API.

### C. Confirm the backend is using PostgreSQL

Open this URL in a browser:

```text
https://lostlink-api.onrender.com/health/ready
```

Expected response:

```json
{
  "status": "ready",
  "database": "postgresql",
  "schema_version": 10,
  "canonical_tables": "ready",
  "storage": "s3"
}
```

The exact schema version may increase with later migrations. In production, `database` must be `postgresql` and `storage` must be `s3`. If it says `sqlite`, the API is **not** connected to your Supabase PostgreSQL database, even if Vercel itself is linked to Supabase. A 503 also indicates that PostgreSQL or the private Storage bucket is unreachable; inspect Render logs and the corresponding environment variables. The endpoint intentionally does not return credentials, hostnames or database names.

### D. Create one real test record from the deployed Vercel site

1. Open the Vercel deployment URL.
2. Submit a clearly identifiable test Lost report, e.g. title `SUPABASE WRITE TEST 2026-11-08`, with a valid test roll number, category, description and campus location.
3. Wait for the success response. Copy the generated public reference. The one-time tracking secret is shown once; keep it private.
4. In Supabase Dashboard → Table Editor → `public.reports`, sort by `created_at` descending and locate the test title/reference.
5. Confirm `submission_channel = public`, `report_type = lost`, `status = open`, and the expected title/category. Confirm a matching attribution row exists in `public.public_roll_identities` (do not expose that table to the browser).
6. In the app, open Track and verify the same report with its reference, roll number and tracking secret.
7. Delete the test report only after completing the verification, using the database/admin process appropriate to the environment. Do not delete records through ad-hoc SQL if dependent audit, notification or reward rows exist.

A successful API response alone proves that the API accepted the write; finding the same reference in Supabase Table Editor proves the record persisted in the intended project. The `/health/ready` response proves the API's configured database driver and schema, not that the Vercel environment points to the right API; check the test reference in the intended Supabase project as the final confirmation.

## 7. Deployment verification

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

## 8. Remaining launch gates

The public workflow is a backend/frontend integration baseline, not yet a complete production launch. Public image and evidence-image upload are pending; existing private image routes remain authenticated. Add CAPTCHA/bot controls, validate roll-number syntax with CVR, agree the in-person verification process, establish retention and deletion policies, tune rate limits, monitor abuse, and complete a security review before college-wide launch.
