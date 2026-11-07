# Supabase Auth + PostgreSQL + Vercel/Render deployment

This is the intended deployment architecture for LostLink:

- **Vercel** serves the static web client from `app/static`.
- **Render** runs the FastAPI API as a persistent container-capable Python web service.
- **Supabase PostgreSQL** is the system of record for application data.
- **Supabase Auth** owns passwords, email verification, sessions and access tokens.
- **Supabase Storage** holds report photos and private claim evidence in a private bucket.
- The FastAPI service remains the policy enforcement point for roles, claims, office review, matching and all database writes.

The browser receives only the Supabase project URL and publishable/anon key. It never receives the database password, S3 credentials or Supabase service-role key.

## 1. Supabase project

Create a Supabase project and configure:

1. PostgreSQL database in a region close to the backend service.
2. Authentication > Providers > Email enabled.
3. Email confirmation enabled.
4. Authentication > URL Configuration: set the Site URL to the Vercel production URL and add the production and preview callback URLs you actually use.
5. Storage bucket named `lostlink-private`; leave **Public bucket** disabled.
6. Storage > S3 access keys: create a dedicated access key for the backend. Store its access key ID and secret only in Render.

Use the project URL and publishable/anon key in the backend configuration. Do not use a service-role key in the frontend or this application configuration.

### PostgreSQL connection

Use the Supabase **Session pooler** connection string for the persistent Render API. Use the host, username, port and database exactly as displayed in Supabase Connect. URL-encode special characters in the password. Set `sslmode=require`.

The application has an ordered schema migration that adds `users.supabase_user_id`. On first boot it creates the schema and applies migrations. Back up the database before first production boot and verify the migration output in service logs.

## 2. Supabase Auth and roles

Set these backend variables:

- `AUTH_PROVIDER=supabase`
- `SUPABASE_URL=https://<project-ref>.supabase.co`
- `SUPABASE_ANON_KEY=<publishable-or-anon-key>`
- `SUPABASE_REQUIRE_CONFIRMED_EMAIL=true`
- `OFFICE_USER_EMAILS=<comma-separated exact office email addresses>`

The browser signs in or signs up with Supabase Auth. It sends the access token to FastAPI as a Bearer token. FastAPI validates it against Supabase Auth's `/auth/v1/user` endpoint before resolving the LostLink profile.

A newly verified identity is provisioned as a **student** by default. The only office-role assignment is an exact email match in the server-side `OFFICE_USER_EMAILS` allowlist. Never accept a role from browser metadata, signup forms, or a user-editable profile field. Remove office addresses from the allowlist to prevent future provisioning as office; existing role downgrades require an explicit administrative process.

For institutional onboarding, configure Supabase email delivery, allowed email domains, abuse protection and rate limits. The current implementation does not perform a college SIS/roll-number verification.

## 3. Private Supabase Storage

Configure:

- `UPLOAD_STORAGE_BACKEND=s3`
- `S3_BUCKET=lostlink-private`
- `S3_ENDPOINT_URL=https://<project-ref>.storage.supabase.co/storage/v1/s3`
- `S3_REGION=<region shown by Supabase Storage S3 settings>`
- `S3_ACCESS_KEY_ID=<dedicated backend key>`
- `S3_SECRET_ACCESS_KEY=<dedicated backend secret>`
- `S3_PREFIX=lostlink`

The storage adapter uses SigV4 and path-style addressing. Use the dedicated `.storage.supabase.co` hostname and copy the exact region from Supabase's S3 settings. Supabase S3 access keys bypass Storage RLS and have broad bucket access, so they are server-only secrets. Objects are stored under opaque keys; the database stores keys, not public URLs. Reads remain behind the authenticated FastAPI routes. Never make this bucket public.

## 4. Deploy the API on Render

1. Import this repository into Render and select the `codex/supabase-final-infrastructure` branch for the initial staging deployment.
2. Use the included `render.yaml` blueprint.
3. Set the required secret values when Render prompts:
   - `DATABASE_URL` (Supabase session-pooler URL)
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `OFFICE_USER_EMAILS`
   - `FRONTEND_ORIGINS` (the exact Vercel origin, no trailing slash)
   - `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`
4. Confirm the service health check `/health/ready` returns HTTP 200.
5. Copy the HTTPS API origin, for example `https://lostlink-api.onrender.com`.

The starter instance is a deployment baseline, not a capacity guarantee. Measure concurrency, memory, matching latency and database pool usage with representative campus traffic before a public launch.

## 5. Deploy the frontend on Vercel

1. Import the same repository into Vercel.
2. Set the project root to the repository root.
3. Set the production branch to the reviewed release branch.
4. Add build environment variable `BACKEND_ORIGIN=https://<your-render-api-origin>`.
5. Keep the build command and output directory from `vercel.json`: `python3 scripts/build_vercel_frontend.py` and `app/static`.
6. Deploy. The build creates `deployment-config.js` with the public API origin; it contains no credentials.

Set the exact Vercel production origin in Render's `FRONTEND_ORIGINS`. If you use preview deployments, add only the specific preview origins you intend to trust. Do not use a broad wildcard for production.

## 6. Required environment on the API

| Variable | Required value |
|---|---|
| `AUTH_PROVIDER` | `supabase` |
| `DEMO_MODE` | `false` |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Publishable/anon key |
| `SUPABASE_REQUIRE_CONFIRMED_EMAIL` | `true` |
| `OFFICE_USER_EMAILS` | Exact office emails |
| `DATABASE_URL` | Supabase PostgreSQL session-pooler URL |
| `DATABASE_POOL_MAX_SIZE` | Start at 3; tune from measured connections |
| `UPLOAD_STORAGE_BACKEND` | `s3` |
| `S3_BUCKET` | `lostlink-private` |
| `S3_ENDPOINT_URL` | Supabase S3 endpoint |
| `S3_REGION` | Region shown in Supabase |
| `S3_ACCESS_KEY_ID` | Backend-only credential |
| `S3_SECRET_ACCESS_KEY` | Backend-only credential |
| `FRONTEND_ORIGINS` | Exact Vercel origin |
| `ALLOWED_HOSTS` | Exact Render API hostname |
| `SESSION_SECRET` | Unique random value (still required by current app middleware) |
| `SESSION_HTTPS_ONLY` | `true` |
| `REQUIRE_REQUEST_ORIGIN` | `true` |

Do not set `DEMO_MODE=true` in a deployed environment. The frontend does not silently fall back to the mock application when a configured remote API is unavailable.

## 7. Release verification checklist

Before accepting real campus data, verify all of the following in staging:

- [ ] Fresh Supabase database migration completes from empty schema.
- [ ] Existing database upgrade path is tested against a restored copy.
- [ ] Email signup, confirmation, sign-in, token refresh and sign-out work.
- [ ] Unverified identities are rejected by FastAPI.
- [ ] Ordinary signups are students; only allowlisted verified emails receive office role.
- [ ] A student cannot promote their own role through user metadata or API input.
- [ ] Student A cannot read Student B's private claim evidence.
- [ ] Office-only routes reject student tokens.
- [ ] Report images upload to the private bucket and remain viewable through authenticated routes.
- [ ] Claim evidence uploads, watermarks and authenticated retrieval work.
- [ ] Image deletion and database/object consistency are tested.
- [ ] Cross-origin browser requests work only from configured Vercel origins.
- [ ] API host allowlist and HTTPS cookies/security headers are correct.
- [ ] Backups and a database-plus-object-storage restore drill are complete.
- [ ] Rate limits, email delivery, monitoring and alert ownership are configured.
- [ ] Load tests measure concurrent API requests, database connections, image throughput and AI inference latency.

This configuration is an implementation baseline. It is not a claim that the external Supabase, Render or Vercel projects have been created or validated; those require the project owner's provider accounts and credentials.
