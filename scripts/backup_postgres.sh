#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${DATABASE_URL:?Set DATABASE_URL to the PostgreSQL database to back up}"
: "${AGE_RECIPIENT:?Set AGE_RECIPIENT to the public age recipient key for encrypted backups}"
command -v pg_dump >/dev/null || { echo "pg_dump is required" >&2; exit 2; }
command -v pg_restore >/dev/null || { echo "pg_restore is required" >&2; exit 2; }
command -v age >/dev/null || { echo "age is required for encrypted backups" >&2; exit 2; }

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
case "$RETENTION_DAYS" in
  ''|*[!0-9]*) echo "RETENTION_DAYS must be a non-negative integer" >&2; exit 2 ;;
esac

mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
plain_file="$(mktemp "${TMPDIR:-/tmp}/lostlink-backup.XXXXXX.dump")"
backup_name="lostlink-$timestamp.dump.age"
backup_file="$BACKUP_DIR/$backup_name"
manifest="$backup_file.sha256"
cleanup() { rm -f "$plain_file"; }
trap cleanup EXIT

pg_dump --format=custom --no-owner --no-acl --dbname="$DATABASE_URL" --file="$plain_file"
pg_restore --list "$plain_file" >/dev/null
age --encrypt --recipient "$AGE_RECIPIENT" --output "$backup_file" "$plain_file"
(
  cd "$BACKUP_DIR"
  sha256sum "$backup_name" > "$backup_name.sha256"
)
chmod 600 "$backup_file" "$manifest"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'lostlink-*.dump.age' -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'lostlink-*.dump.age.sha256' -mtime "+$RETENTION_DAYS" -delete

printf 'Encrypted database backup created: %s\n' "$backup_file"
printf 'Keep the decryption identity separately and securely. Back up the private uploads volume separately; pg_dump contains database records only.\n'
