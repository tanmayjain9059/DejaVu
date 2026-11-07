#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${AGE_RECIPIENT:?Set AGE_RECIPIENT to the public age recipient key}"
command -v age >/dev/null || { echo "age is required for encrypted backups" >&2; exit 2; }
command -v tar >/dev/null || { echo "tar is required" >&2; exit 2; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
case "$RETENTION_DAYS" in
  ''|*[!0-9]*) echo "RETENTION_DAYS must be a non-negative integer" >&2; exit 2 ;;
esac

temporary_root="$(mktemp -d "${TMPDIR:-/tmp}/lostlink-supabase-backup.XXXXXX")"
cleanup() { rm -rf "$temporary_root"; }
trap cleanup EXIT

python3 "$SCRIPT_DIR/export_object_storage.py" --destination "$temporary_root/uploads"
UPLOADS_DIR="$temporary_root/uploads" \
  BACKUP_DIR="$BACKUP_DIR" RETENTION_DAYS="$RETENTION_DAYS" \
  AGE_RECIPIENT="$AGE_RECIPIENT" bash "$SCRIPT_DIR/backup_uploads.sh"

echo "Supabase Storage export encrypted. Keep this archive with the matching PostgreSQL backup."
