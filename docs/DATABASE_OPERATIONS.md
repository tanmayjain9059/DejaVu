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

The current startup bootstrap records a `schema_migrations` baseline row. Existing additive schema compatibility updates remain in the startup bootstrap; a formal ordered schema-migration runner and rollback policy remain a release gate for future schema changes.

## PostgreSQL backups

Install PostgreSQL client utilities matching your supported server version and [age](https://age-encryption.org/). Create an age key pair and store the private identity separately from the backups. Set `AGE_RECIPIENT` to the public recipient key and `DATABASE_URL` through your secret manager or an untracked shell environment variable, then run:

```bash
AGE_RECIPIENT=age1... BACKUP_DIR=/secure/backups RETENTION_DAYS=14 scripts/backup_postgres.sh
```

The script creates a custom-format dump, encrypts it with `age`, checks that `pg_restore` can read its catalog before encryption, writes a SHA-256 manifest, and applies local retention. Copy the encrypted artifacts to access-controlled storage in a separate failure domain and monitor freshness/failures. Protect the connection string, recipient identity, and backup files.

The database dump does not include uploaded photos or private claim evidence. Back up the named Docker uploads volume or the configured storage provider using a coordinated snapshot/backup plan. Keep the database dump and corresponding upload snapshot together.

## Restore drill

Restore only into a separate disposable database first:

```bash
RESTORE_CONFIRM=YES DATABASE_URL='postgresql://...' \
  scripts/restore_postgres.sh /secure/backups/lostlink-YYYYMMDDTHHMMSSZ.dump
```

This operation is destructive to objects in the selected target database. Confirm the target twice before setting `RESTORE_CONFIRM=YES`. Restore the matching uploads backup separately, then test `/health/ready`, row counts, foreign-key integrity, login, claim approval, handover, and private evidence access. Record the drill date, duration, data-loss window, and any recovery issues.

## Operational release gates

- Monitor backup freshness, restore outcomes, disk usage, DB connection pool saturation, query latency, failed logins, HTTP 5xx, and readiness failures.
- Set and test a retention/deletion schedule for account data, reports, images, evidence, and audit events.
- Rotate secrets using the provider's procedure and verify old credentials are revoked.
- Never log connection strings, session secrets, raw private evidence, or sensitive item details.
