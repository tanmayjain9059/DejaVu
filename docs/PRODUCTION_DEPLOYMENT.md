# LostLink production deployment runbook

This is a deployment baseline. A successful container start is not a security audit or a substitute for a staging rehearsal.

## Required infrastructure

- A supported PostgreSQL instance with automated backups, TLS, restricted network access, and a tested restore procedure.
- A public HTTPS reverse proxy/load balancer with a valid certificate. The application container binds to localhost only; terminate TLS at the proxy and preserve the original host. Do not expose port 8000 directly to the internet.
- Persistent, private storage for report images and claim evidence. This compose file uses a named Docker volume. Back up that volume together with the database; database dumps alone do not include images.
- Secret management for `SESSION_SECRET` and `DATABASE_URL`. Never commit actual credentials or put them in logs.
- A verified canonical hostname and DNS, monitoring/alerts, a retention/deletion policy, and an incident response owner.

## Configure and deploy

Create an untracked deployment `.env` file containing:

```dotenv
DATABASE_URL=postgresql://<user>:<url-encoded-password>@<host>:5432/<database>?sslmode=require
SESSION_SECRET=<unique-random-secret>
ALLOWED_HOSTS=lostlink.example.edu
APP_PORT=8000
DATABASE_POOL_MAX_SIZE=5
```

Replace the example hostname and URL with real provider values. URL-encode special characters in the database password. Do not use the local development password. Ensure the PostgreSQL provider accepts connections only from the deployment host/network.

Build and start:

```bash
docker compose -f compose.production.yml up -d --build
docker compose -f compose.production.yml ps
docker compose -f compose.production.yml logs --tail=100 app
```

Configure the reverse proxy to forward HTTPS traffic to `127.0.0.1:8000`, preserve the public `Host`, and set the standard forwarded-protocol headers. Verify the proxy, host allowlist, cookie Secure flag, and HTTPS redirect in staging before production. Do not trust arbitrary forwarded headers from public clients.

## Pre-launch checks

1. Run the CI workflow for the exact commit to deploy.
2. Verify `/health/live` and `/health/ready` through the intended proxy path.
3. Test student and office roles, cross-account access, private evidence image access, login lockouts, claim disputes, approval, and duplicate handover.
4. Run a restore drill for PostgreSQL **and** the uploads volume; verify row counts, relationships, and that evidence is still private.
5. Confirm migration from SQLite is separately rehearsed using the explicit migration command and a backup of the source.
6. Set monitoring for error rates, readiness failures, disk usage, database connections, lock contention, backup freshness, and upload failures.
7. Define retention/deletion rules and obtain campus approval before real personal or sensitive item data is entered.

## Backup and restore

See [database and upload backup operations](DATABASE_OPERATIONS.md). PostgreSQL dumps are encrypted with age before retention; store encrypted artifacts off-host with access controls. A PostgreSQL dump does not contain the upload volume. Test restoration on an isolated database before relying on backups.

## Limits that require environment-specific validation

- This repository cannot provision your provider, DNS, TLS certificate, secret store, monitoring, or off-host backup destination.
- The app currently stores upload paths in the database and image bytes on the configured filesystem. The uploads volume must be included in backups and kept private.
- The existing SQL compatibility adapter and advisory lock need workload testing; run concurrency/load tests on staging before high-traffic use.
- Existing SQLite records are not moved automatically. Use the reviewed migration script and verify images and row counts.
- Matching quality needs a representative, privacy-reviewed labelled dataset; a passing synthetic benchmark is not proof of production accuracy.
