# Free-tier deployment baseline

This guide targets a **$0/month demonstration or small supervised pilot**, not a production deployment for sensitive campus records. Free-tier limits and provider terms can change; check the linked provider pages before provisioning.

## Recommended split

| Component | Free-tier option | Why |
|---|---|---|
| FastAPI application | Render Free Web Service | Runs the existing Python application from this repository's Dockerfile |
| Relational database | Neon Free PostgreSQL | Keeps application records outside the web service's disposable filesystem |
| Private image/evidence storage | Cloudflare R2 Standard | Keeps report photos and private claim evidence outside the disposable app container |

Do **not** use Render's Free PostgreSQL for this project: it expires 30 days after creation and has no backups. Render Free Web Services also spin down after 15 minutes without traffic, may restart, and lose local filesystem changes on restart, redeploy, or spin-down. They can take about a minute to wake up. Use Neon for the database and a private S3-compatible bucket for uploads instead.

Provider references:
- [Render free service limits](https://render.com/docs/free)
- [Neon Free plan limits](https://neon.com/docs/introduction/plans)
- [Cloudflare R2 pricing and free allowance](https://developers.cloudflare.com/r2/pricing/)

## Provision the services

1. Create a Neon project and database. Copy its **pooled** PostgreSQL connection string. Neon Free currently lists 1 GB storage per project, 100 compute-hours per month, and 5 GB public network transfer per month. Compute can scale to zero; the first request after inactivity may wait for it to wake.
2. Create a Cloudflare R2 bucket. Keep it **private**; do not enable public bucket access. Create an API token restricted to this bucket with object read/write permissions. Copy the S3 endpoint and access credentials.
3. Create a Render Web Service from this GitHub repository and select the Free instance. Use the repository Dockerfile. Set the branch to the integration branch you intend to deploy after testing and merging.

## Render environment variables

Set these in the Render service dashboard. Do not commit real credentials.

\`\`\`dotenv
DATABASE_URL=<Neon pooled PostgreSQL URL with sslmode=require>
DATABASE_POOL_MAX_SIZE=2
SESSION_SECRET=<unique random secret, at least 32 random bytes>
SESSION_HTTPS_ONLY=true
REQUIRE_REQUEST_ORIGIN=true
DEMO_MODE=false
ALLOWED_HOSTS=<your exact Render hostname>
OBJECT_STORAGE_BUCKET=<private R2 bucket name>
OBJECT_STORAGE_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
OBJECT_STORAGE_ACCESS_KEY_ID=<R2 access key>
OBJECT_STORAGE_SECRET_ACCESS_KEY=<R2 secret key>
OBJECT_STORAGE_REGION=auto
USE_SEMANTIC_MODEL=false
USE_CLIP_MODEL=false
\`\`\`

Generate a session secret locally:

\`\`\`bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
\`\`\`

The application uses SQLite and local uploads only when no external database/object storage is configured. On Render Free, **do not leave either fallback enabled for real records or uploaded images**: local files are disposable. The S3-compatible storage adapter stores report photos and private claim evidence in the private bucket, then serves them through LostLink's authenticated, access-checked routes. Images are not served from public bucket URLs.

The \`DATABASE_URL\` must be a PostgreSQL URL. Keep the Neon pooled connection string and a small application pool size to avoid exhausting free compute connections. The application creates/updates its schema on startup; confirm readiness after the first deploy.

## Verify before sharing the demo

1. Confirm \`/health/live\` and \`/health/ready\` return success.
2. Create a student account using an office-issued registration invite.
3. Submit a lost report and a found report; upload an image to each.
4. Confirm a student cannot view private claim evidence or restricted-category photos, and that office staff can review evidence through the application.
5. Submit a claim with an evidence photo and verify that it remains available after a Render redeploy or service spin-down.
6. Confirm that report metadata remains after a Render restart and a new application deployment.
7. Check Neon storage/compute/network quotas and R2 storage/operation usage.

## Cost and operational limits

- This is a free-tier demo target, not an uptime guarantee. Render Free sleeps after inactivity and can cold-start slowly.
- Neon Free can suspend compute after monthly compute or network-transfer quotas are reached. Its storage limit is finite; monitor usage.
- R2's free Standard allowance is 10 GB-month storage, 1 million Class A operations and 10 million Class B operations per month. Usage beyond the free allowance can incur charges; set account billing/usage alerts and monitor it.
- Render warns that unusually high service-initiated external traffic, including traffic to databases and object storage, can lead to a free service being suspended. Keep the pilot's traffic modest.
- Free tiers do not provide the backup, retention, incident response, availability, or contractual assurances needed for institutional personal data. Do not enter real identity documents, sensitive ownership evidence, or other production personal data until the college approves the deployment and a tested backup/restore plan exists.
- Matching models remain disabled by default. Do not enable CLIP/MiniLM on the small free web instance; their model downloads and memory use can exceed free compute limits.
- If the pilot becomes important or data-sensitive, move to paid persistent compute, managed PostgreSQL with backups, and object storage with a documented backup/retention policy before continuing.

## Existing data

This guide does not automatically migrate a local SQLite database or its upload directory. Use the reviewed [SQLite-to-PostgreSQL migration procedure](DATABASE_OPERATIONS.md) for the database migration. The existing migration utility copies local files to a local destination directory; it does not upload them to R2. After migrating the database, configure the R2 variables locally and copy the referenced files with a dry run first:

```bash
python scripts/migrate_uploads_to_object_storage.py \
  --database ./data/lostlink.db \
  --source-uploads ./data/uploads
```

If the inventory is correct, repeat with `--execute`. The script preserves the filenames already stored in the database, so the hosted app can resolve the same keys from R2. Keep the source database and uploads directory until hosted report photos and private claim evidence have been verified. A migration rehearsal and independent count verification are required before using existing records on a hosted service.
