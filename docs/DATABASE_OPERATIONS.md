# Database migration, backup, and recovery

## SQLite to PostgreSQL migration

Use a fresh, empty PostgreSQL database. Schedule a maintenance window and stop writes to the source app before the final migration.

1. Back up the SQLite database file and the entire private uploads directory. Keep a verified copy off-host.
2. Configure `DATABASE_URL` for the target PostgreSQL database and `UPLOAD_DIR` for the target's persistent private uploads volume. Keep the source SQLite file untouched.
3. Run a dry run first:

   ```bash
   python scripts/migrate_sqlite_to_postgres.py \
     --source-db ./data/lostlink.db \
     --source-uploads ./data/uploads
   ```

4. Review the printed source table counts and referenced upload count. The script refuses unknown source tables, a corrupt SQLite file, source foreign-key violations, missing referenced uploads, unsafe upload paths, or a non-empty destination.
5. Run the actual copy:

   ```bash
   python scripts/migrate_sqlite_to_postgres.py \
     --source-db ./data/lostlink.db \
     --source-uploads ./data/uploads \
     --execute
   ```

6. Verify row counts, application health, student/office access, claims, notifications, handovers, audit history, and private image access in staging. Reconcile source and destination counts independently.
7. Keep the source read-only and available for rollback until the owner signs off. Do not point production traffic at the destination until the staging rehearsal passes.

The utility copies known application tables in dependency order and the image files referenced by report/evidence records. It does not delete or modify the SQLite source. It deliberately does not merge into a populated PostgreSQL database. Run a rehearsal with a recent copy of production data before the final maintenance-window migration.

The startup bootstrap records the legacy schema as version 1; an ordered forward-only migration runner applies version 2 (active-claim lookup indexes) and records applied versions. Existing additive compatibility updates still run in the legacy bootstrap. Future migrations must be appended with a new version and a safe, idempotent operation; a per-migration rollback/recovery policy remains a release gate.

## PostgreSQL backups

Install PostgreSQL client utilities matching your supported server version and [age](https://age-encryption.org/). Create an age key pair and store the private identity separately from the backups. Set `AGE_RECIPIENT` to the public recipient key and `DATABASE_URL` through your secret manager or an untracked shell environment variable, then run:

```bash
AGE_RECIPIENT=age1... BACKUP_DIR=/secure/backups RETENTION_DAYS=14 bash scripts/backup_postgres.sh
```

The script creates a custom-format dump, encrypts it with `age`, checks that `pg_restore` can read its catalog before encryption, writes a SHA-256 manifest, and applies local retention. Copy the encrypted artifacts to access-controlled storage in a separate failure domain and monitor freshness/failures. Protect the connection string, recipient identity, and backup files.

The database dump does not include uploaded photos or private claim evidence. Back up the named Docker uploads volume or the configured storage provider using a coordinated snapshot/backup plan. Keep the database dump and corresponding upload snapshot together.

## Optional daily backup schedule (self-hosted Linux)

The repository includes hardened systemd service/timer templates in `deploy/systemd/`. Use these only if the database is reachable from a Linux backup host; managed platforms may instead use their native scheduler.

1. Install PostgreSQL client utilities and `age` on the backup host.
2. Create a dedicated `lostlink-backup` system user/group and directories for the script checkout, secret file, and backups. Make the backup directory writable only by that account and administrators.
3. Create `/etc/lostlink/backup.env` with mode `0640`, owned by `root:lostlink-backup`, containing:

   ```dotenv
   DATABASE_URL=postgresql://<user>:<url-encoded-password>@<host>:5432/<database>?sslmode=require
   AGE_RECIPIENT=age1...
   BACKUP_DIR=/var/backups/lostlink
   RETENTION_DAYS=14
   ```

   Use the real provider URL and public age recipient. Keep the private age identity off this host. Do not commit the environment file.
4. Install the service and timer from `deploy/systemd/` into `/etc/systemd/system/`, then run `systemctl daemon-reload` and `systemctl enable --now lostlink-backup.timer`.
5. Verify `systemctl list-timers lostlink-backup.timer`, run `systemctl start lostlink-backup.service` once, and inspect `journalctl -u lostlink-backup.service`. Configure an external alert for failed units and stale backup timestamps.
6. Copy encrypted dumps and checksum manifests to a separate encrypted/access-controlled failure domain. A local timer and local retention are not a substitute for off-host backups.

The timer is a template, not activated by this repository. The uploads volume must have its own coordinated backup schedule.

## Restore drill

Restore only into a separate disposable database first:

```bash
RESTORE_CONFIRM=YES DATABASE_URL='postgresql://...' \
  bash scripts/restore_postgres.sh /secure/backups/lostlink-YYYYMMDDTHHMMSSZ.dump.age
```

This operation is destructive to objects in the selected target database. Confirm the target twice before setting `RESTORE_CONFIRM=YES`. Restore the matching uploads backup separately, then test `/health/ready`, row counts, foreign-key integrity, login, claim approval, handover, and private evidence access. Record the drill date, duration, data-loss window, and any recovery issues.

## Operational release gates

- Monitor backup freshness, restore outcomes, disk usage, DB connection pool saturation, query latency, failed logins, HTTP 5xx, and readiness failures.
- Set and test a retention/deletion schedule for account data, reports, images, evidence, and audit events.
- Rotate secrets using the provider's procedure and verify old credentials are revoked.
- Never log connection strings, session secrets, raw private evidence, or sensitive item details.
