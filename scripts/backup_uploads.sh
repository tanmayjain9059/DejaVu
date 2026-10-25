#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${UPLOADS_DIR:?Set UPLOADS_DIR to the private uploads directory}"
: "${AGE_RECIPIENT:?Set AGE_RECIPIENT to the public age recipient key}"
command -v tar >/dev/null || { echo "tar is required" >&2; exit 2; }
command -v age >/dev/null || { echo "age is required for encrypted backups" >&2; exit 2; }
[[ -d "$UPLOADS_DIR" ]] || { echo "UPLOADS_DIR does not exist: $UPLOADS_DIR" >&2; exit 2; }
if find "$UPLOADS_DIR" -type l -print -quit | grep -q .; then
  echo "Refusing to archive symlinks in private uploads storage." >&2
  exit 2
fi

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
case "$RETENTION_DAYS" in
  ''|*[!0-9]*) echo "RETENTION_DAYS must be a non-negative integer" >&2; exit 2 ;;
esac
mkdir -p "$BACKUP_DIR"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
plain_file="$(mktemp "${TMPDIR:-/tmp}/lostlink-uploads.XXXXXX")"
backup_name="lostlink-uploads-$timestamp.tar.gz.age"
backup_file="$BACKUP_DIR/$backup_name"
manifest="$backup_file.sha256"
cleanup() { rm -f "$plain_file"; }
trap cleanup EXIT

tar --create --gzip --file="$plain_file" --directory="$UPLOADS_DIR" --one-file-system -- .
tar --list --gzip --file="$plain_file" >/dev/null
age --encrypt --recipient "$AGE_RECIPIENT" --output "$backup_file" "$plain_file"
(
  cd "$BACKUP_DIR"
  sha256sum "$backup_name" > "$backup_name.sha256"
)
chmod 600 "$backup_file" "$manifest"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'lostlink-uploads-*.tar.gz.age' -mtime "+$RETENTION_DAYS" -delete
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'lostlink-uploads-*.tar.gz.age.sha256' -mtime "+$RETENTION_DAYS" -delete

printf 'Encrypted private uploads backup created: %s\n' "$backup_file"
printf 'Coordinate this snapshot with the matching database backup; pause writes or use a consistent storage snapshot.\n'
