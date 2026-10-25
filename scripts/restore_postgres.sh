#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${DATABASE_URL:?Set DATABASE_URL to the disposable restore target}"
: "${RESTORE_CONFIRM:?Set RESTORE_CONFIRM=YES only after verifying the target database}"
BACKUP_FILE="${1:?Usage: RESTORE_CONFIRM=YES DATABASE_URL=... scripts/restore_postgres.sh path/to/backup.dump}"

if [[ "$RESTORE_CONFIRM" != "YES" ]]; then
  echo "Restore refused. Set RESTORE_CONFIRM=YES only for an intentionally selected disposable target." >&2
  exit 2
fi
if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file does not exist: $BACKUP_FILE" >&2
  exit 2
fi
if [[ -f "$BACKUP_FILE.sha256" ]]; then
  sha256sum --check "$BACKUP_FILE.sha256"
fi
pg_restore --list "$BACKUP_FILE" >/dev/null

cat >&2 <<'WARNING'
WARNING: this operation drops/recreates objects in the target database.
Use a separate, disposable restore target first. It does not restore image files.
WARNING
pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --dbname="$DATABASE_URL" "$BACKUP_FILE"
echo "Database restore completed. Verify health, row counts, application workflows, and matching uploads before cutover."
