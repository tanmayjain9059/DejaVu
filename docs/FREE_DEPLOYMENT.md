# Oracle Cloud + Supabase deployment

This is LostLink's target self-managed hosting path. Render was used for the prototype; it is not the production deployment target.

The baseline aims for **$0/month within provider free-tier quotas** for a small demo or supervised pilot. The Oracle deployment builds the optional ML dependencies and enables MiniLM semantic text ranking by default; CLIP is implemented and test-covered but remains opt-in because its per-candidate CPU inference can add noticeable latency on a small VM. Free-tier capacity, regional availability, account eligibility and terms can change. It is not an uptime or backup guarantee and is not approved for sensitive institutional data.

## Target architecture

| Layer | Service | Responsibility |
|---|---|---|
| Domain and DNS | Your domain registrar/DNS provider | Public hostname points to the Oracle VM |
| Compute | Oracle Cloud Infrastructure Always Free Ampere A1 | Runs Docker Compose, FastAPI and Caddy |
| Database | Supabase Free PostgreSQL | Users, reports, claims, evidence metadata, audit and rewards |
| Object storage | Supabase Storage private bucket | Report photos and private claim evidence |
| TLS/reverse proxy | Caddy on the Oracle VM | Automatic HTTPS and reverse proxy to FastAPI |

Oracle documents an Always Free Ampere A1 allowance equivalent to 2 OCPUs and 12 GB RAM, subject to tenancy and home-region capacity. Oracle may reclaim idle Always Free compute instances when the documented low-utilisation conditions are met. Do not treat this as guaranteed hosting capacity. See [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) and [Oracle Free Tier FAQ](https://www.oracle.com/apac/cloud/free/faq/).

Supabase Free currently provides a small managed PostgreSQL database and Storage allowance, but free projects can be paused after a period of inactivity. Free tier does not include automatic database backups. Check [Supabase pricing](https://supabase.com/pricing) and [Free plan limits](https://supabase.com/docs/guides/platform/billing-on-supabase).

## Why this fits the current code

- LostLink already supports PostgreSQL through `DATABASE_URL`; local SQLite remains the development default.
- `app/core/object_storage.py` supports private S3-compatible object storage. Supabase exposes an S3-compatible endpoint, but it requires path-style addressing. The adapter configures that explicitly.
- Supabase's S3 endpoint uses AWS Signature Version 4. Its S3 access keys bypass Storage RLS and have broad bucket access, so keep them only in the FastAPI server environment. Never put them in frontend JavaScript.
- Report photos and claim evidence continue to be served through LostLink's authenticated, access-checked routes. Do not make the bucket public.
- Caddy terminates HTTPS for your domain. FastAPI is exposed only on the internal Docker network.

Provider documentation:
- [Supabase S3 compatibility](https://supabase.com/docs/guides/storage/s3/compatibility)
- [Supabase S3 authentication and required path-style addressing](https://supabase.com/docs/guides/storage/s3/authentication)
- [Supabase Storage access controls](https://supabase.com/docs/guides/storage/security/access-control)
- [Oracle Always Free compute](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)

## 1. Create the Supabase project

1. Create a Supabase project in a region reasonably close to your expected users and Oracle VM. Record the database password securely.
2. Open **Project Settings → Database → Connection string**. Select the **Session pooler** connection string for an IPv4-compatible VM connection. Use the URI format shown by Supabase and append/retain `sslmode=require`. Do not use the direct database host if your VM network cannot reach its IPv6 endpoint. Keep the pooler mode consistent with the selected connection string.
3. Open **Storage** and create a private bucket named `lostlink-private`. Do not enable public access.
4. Open **Storage → S3** settings, enable the S3 protocol if prompted, and generate S3 access credentials. Save the access key and secret immediately.
5. Copy the S3 endpoint and region exactly as displayed. The endpoint normally has this shape: `https://<project-ref>.storage.supabase.co/storage/v1/s3`. Do not guess the region.
6. Keep the database password, S3 secret and service credentials out of Git and out of the browser.

Supabase S3 access keys bypass Storage RLS. The LostLink server therefore owns the bucket credentials and enforces the existing report/claim privacy checks before returning any image.

## Matching AI runtime

The Oracle Compose build sets `INSTALL_ML=true`, installing Sentence Transformers and Transformers dependencies with CPU-only PyTorch wheels (no CUDA packages), suitable for a CPU VM. It enables `USE_SEMANTIC_MODEL=true` with `sentence-transformers/all-MiniLM-L6-v2`, running on CPU. The Hugging Face cache is persisted in the `huggingface-cache` Docker volume so model weights are not downloaded on every restart. First model use downloads the weights; allow outbound HTTPS to the Hugging Face Hub. Confirm the office match response reports `sentence_embeddings` as its matching engine. If the model cannot load, LostLink deliberately falls back to `lexical_baseline`; that is a degraded mode, not semantic AI.

CLIP (`openai/clip-vit-base-patch32`) is supported by the installed Transformers/PyTorch dependencies. It is disabled by default on the free-tier VM because it performs image inference candidate-by-candidate for up to 25 shortlisted records. Enable `USE_CLIP_MODEL=true` only after measuring request latency and RAM. The image matching path passes storage object keys—not local filesystem paths—to the private storage adapter. CI loads the actual pretrained CLIP weights and smoke-tests both two-photo and one-photo-versus-text inference branches. This validates model loading and tensor compatibility; it is not a campus image-retrieval quality benchmark.

The CI matching-evaluation job must load MiniLM successfully; it is a required check rather than an allowed-to-fail optional job.

## 3. Create the Oracle VM

1. Create an Oracle Cloud account and use the Always Free resources in your tenancy's **home region**.
2. Attempt an Ampere A1 VM with 2 OCPUs and 12 GB RAM if available. Host capacity is not guaranteed; if the shape is unavailable, retry later or choose another supported Always Free shape/size.
3. Use Ubuntu 22.04/24.04 ARM64 (aarch64). The repository's Python Docker base image supports ARM64.
4. Assign a public IPv4 address. Configure ingress rules for TCP 80 and 443, plus TCP 22 restricted to your own administrator IP address for SSH. Do not expose port 8000 or the Docker daemon.
5. Use SSH keys; disable password SSH login after verifying key access. Apply OS security updates.
6. Install Docker Engine and the Docker Compose plugin using the official Ubuntu instructions.
7. Reserve/retain a stable public IP if your tenancy/network configuration supports it; otherwise update DNS if the VM's public IP changes.

## 4. Point your domain to the VM

At your DNS provider, create:
- An `A` record for the chosen hostname (for example `lostlink.example.in`) pointing to the VM public IPv4 address.
- Optionally, a `www` record pointing to the canonical hostname.

Wait for DNS to resolve before starting Caddy. The hostname must be the exact value used in the `DOMAIN` environment variable. Caddy obtains and renews the HTTPS certificate automatically when ports 80 and 443 are reachable.

## 5. Configure the deployment

On the VM, clone the repository and check out the integration branch only after you have reviewed and merged PR #3 yourself. Do not deploy from an unmerged branch for a public pilot.

Create `.env.oracle` from `.env.oracle.example`. Fill in:
- `DOMAIN`: your real public hostname.
- `DATABASE_URL`: the Supabase Session Pooler URI with URL-encoded password and `sslmode=require`.
- `OBJECT_STORAGE_BUCKET`: the private bucket name.
- `OBJECT_STORAGE_ENDPOINT_URL`: the exact Supabase S3 endpoint.
- `OBJECT_STORAGE_ACCESS_KEY_ID` and `OBJECT_STORAGE_SECRET_ACCESS_KEY`: server-side S3 credentials.
- `OBJECT_STORAGE_REGION`: the exact Supabase S3 region.
- `SESSION_SECRET`: generate a unique random secret with `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

Set restrictive file permissions: `chmod 600 .env.oracle`. Never commit this file.

The production app refuses to start if PostgreSQL or remote object storage is missing, if the object endpoint is not HTTPS, or if demo seeding is enabled. This prevents an accidental silent fallback to ephemeral local SQLite/uploads.

## 6. Start the application

From the repository root:

```bash
docker compose --env-file .env.oracle -f compose.oracle.yml config
docker compose --env-file .env.oracle -f compose.oracle.yml up -d --build
docker compose --env-file .env.oracle -f compose.oracle.yml ps
docker compose --env-file .env.oracle -f compose.oracle.yml logs --tail=100 app caddy
```

The app container is not published on a host port. Caddy is the only public entry point and proxies to FastAPI over the private Compose network.

Check:
- `https://<your-domain>/health/live`
- `https://<your-domain>/health/ready`

Readiness verifies both the PostgreSQL connection and the configured private storage bucket. Do not consider the deployment ready if either check fails.

## 7. First-run acceptance test

1. Create an office account through the controlled bootstrap process; do not enable public office registration.
2. Create a registration invite and register a student.
3. Submit lost and found reports with photos.
4. Verify images survive app container recreation.
5. Submit a claim with a private evidence image.
6. Verify a different student cannot retrieve private claim evidence, office-only images, or restricted-category photos.
7. Complete office intake, claim review and physical handover using test records.
8. Restart the app container and repeat photo/evidence access checks.
9. Check Supabase database/storage quotas and Oracle instance utilisation.

## 8. Backups, limits and security

- Supabase Free does not include automatic database backups. Schedule encrypted `pg_dump` exports and `scripts/backup_supabase_storage.sh` exports to storage outside the Supabase project and test restores. Do not store the only backup in the same project/account.
- Supabase Storage S3 compatibility does not provide S3 object versioning. Use `scripts/backup_supabase_storage.sh` to export the private bucket and create an encrypted archive; see [DATABASE_OPERATIONS.md](DATABASE_OPERATIONS.md). Keep an independent encrypted copy of uploads if they become important.
- Free-tier quotas are finite and can change. Monitor database size, storage size, egress, request counts, Oracle resource utilisation and account notices.
- Oracle may reclaim an idle Always Free VM. Keep source code and deployment configuration in Git; keep backups outside the VM.
- Keep CLIP and MiniLM disabled on the baseline VM until measured memory/CPU use demonstrates they fit. The deterministic matching path remains available.
- Configure OS updates, SSH access restrictions, firewall rules, log rotation, disk monitoring and an external uptime check.
- Do not enter real identity documents, sensitive claim evidence or other production personal data until the college approves the service, access controls, retention policy, backup/restore procedure and incident ownership.
- The free deployment is a pilot baseline, not an institutional production SLA.

## Existing local data

Do not point the hosted application at the local SQLite file. Use the reviewed SQLite-to-PostgreSQL migration procedure in [DATABASE_OPERATIONS.md](DATABASE_OPERATIONS.md) against a fresh Supabase database, rehearse with a copy, and independently verify counts and relationships. Then use `scripts/migrate_uploads_to_object_storage.py` with the Supabase S3 settings to dry-run and upload referenced report and claim images. Retain the original SQLite database and uploads until the hosted application has been verified end to end.
