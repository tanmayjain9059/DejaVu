#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${DATABASE_URL:?Set DATABASE_URL to the PostgreSQL database to back up}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

case "$RETENTION_DAYS" in
  ''|*[!0-9]*) echo "RETENTION_DAYS must be a non-negative integer" >&2; exit 2 ;;
esac

mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_file="$BACKUP_DIR/lostlink-$timestamp.dump"
manifest="$backup_file.sha256"

# Custom format supports selective and full pg_restore operations.
pg_dump --format=custom --no-owner --no-acl --dbname="$DATABASE_URL" --file="$backup_file"
pg_restore --list "$backup_file" >/dev/null
sha256sum "$backup_file" > "$manifest"
chmod 600 "$backup_file" "$manifest"

find "$BACKUP_DIR" -maxdepth 1 -type f -name 'lostlink-*.dump' -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'lostlink-*.dump.sha256' -mtime "+$RETENTION_DAYS" -delete

printf 'Database backup created: %s\n' "$backup_file"
printf 'IMPORTANT: back up the private uploads volume separately; pg_dump contains database records only.\n'
