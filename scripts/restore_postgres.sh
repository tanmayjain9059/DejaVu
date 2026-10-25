#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${DATABASE_URL:?Set DATABASE_URL to the disposable restore target}"
: "${RESTORE_CONFIRM:?Set RESTORE_CONFIRM=YES only after verifying the target database}"
BACKUP_FILE="${1:?Usage: RESTORE_CONFIRM=YES DATABASE_URL=... AGE_IDENTITY=... scripts/restore_postgres.sh path/to/backup.dump.age}"

if [[ "$RESTORE_CONFIRM" != "YES" ]]; then
  echo "Restore refused. Set RESTORE_CONFIRM=YES only for an intentionally selected disposable target." >&2
  exit 2
fi
if [[ ! -f "$BACKUP_FILE" ]]; then
  echo "Backup file does not exist: $BACKUP_FILE" >&2
  exit 2
fi
if [[ -f "$BACKUP_FILE.sha256" ]]; then
  (
    cd "$(dirname "$BACKUP_FILE")"
    sha256sum --check "$(basename "$BACKUP_FILE").sha256"
  )
fi
command -v pg_restore >/dev/null || { echo "pg_restore is required" >&2; exit 2; }

plain_file=""
cleanup() { [[ -z "$plain_file" ]] || rm -f "$plain_file"; }
trap cleanup EXIT

case "$BACKUP_FILE" in
  *.age)
    : "${AGE_IDENTITY:?Set AGE_IDENTITY to the private age identity path}"
    command -v age >/dev/null || { echo "age is required to decrypt this backup" >&2; exit 2; }
    plain_file="$(mktemp "${TMPDIR:-/tmp}/lostlink-restore.XXXXXX.dump")"
    chmod 600 "$plain_file"
    age --decrypt --identity "$AGE_IDENTITY" --output "$plain_file" "$BACKUP_FILE"
    BACKUP_TO_RESTORE="$plain_file"
    ;;
  *)
    echo "Refusing an unencrypted backup. Use the encrypted .dump.age artifact." >&2
    exit 2
    ;;
esac

pg_restore --list "$BACKUP_TO_RESTORE" >/dev/null
cat >&2 <<'WARNING'
WARNING: this operation drops/recreates objects in the target database.
Use a separate, disposable restore target first. It does not restore image files.
WARNING
pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --dbname="$DATABASE_URL" "$BACKUP_TO_RESTORE"
echo "Database restore completed. Verify health, row counts, application workflows, and matching uploads before cutover."
