#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${RESTORE_CONFIRM:?Set RESTORE_CONFIRM=YES only after verifying the restore target}"
: "${AGE_IDENTITY:?Set AGE_IDENTITY to the private age identity path}"
UPLOADS_TARGET="${UPLOADS_TARGET:?Set UPLOADS_TARGET to an existing empty directory}"
BACKUP_FILE="${1:?Usage: RESTORE_CONFIRM=YES AGE_IDENTITY=... UPLOADS_TARGET=... bash scripts/restore_uploads.sh backup.tar.gz.age}"

if [[ "$RESTORE_CONFIRM" != "YES" ]]; then
  echo "Restore refused. Set RESTORE_CONFIRM=YES only for an intentionally selected empty target." >&2
  exit 2
fi
[[ -f "$BACKUP_FILE" ]] || { echo "Backup file does not exist: $BACKUP_FILE" >&2; exit 2; }
[[ -d "$UPLOADS_TARGET" && ! -L "$UPLOADS_TARGET" ]] || {
  echo "UPLOADS_TARGET must be an existing real directory, not a symlink." >&2; exit 2;
}
if find "$UPLOADS_TARGET" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
  echo "Refusing to restore into a non-empty directory." >&2
  exit 2
fi
[[ -f "$BACKUP_FILE.sha256" ]] || { echo "Backup checksum manifest is required." >&2; exit 2; }
(
  cd "$(dirname "$BACKUP_FILE")"
  sha256sum --check "$(basename "$BACKUP_FILE").sha256"
)
command -v age >/dev/null || { echo "age is required to decrypt this backup" >&2; exit 2; }
command -v tar >/dev/null || { echo "tar is required" >&2; exit 2; }

plain_file="$(mktemp "${TMPDIR:-/tmp}/lostlink-uploads-restore.XXXXXX")"
staging_dir="$(mktemp -d "$UPLOADS_TARGET/.restore.XXXXXX")"
cleanup() { rm -f "$plain_file"; [[ -z "$staging_dir" ]] || rm -rf "$staging_dir"; }
trap cleanup EXIT
chmod 600 "$plain_file"
age --decrypt --identity "$AGE_IDENTITY" --output "$plain_file" "$BACKUP_FILE"

# The app stores flat, generated filenames. Reject traversal, links, devices, and nested paths.
python3 - "$plain_file" <<'PY'
import sys
import tarfile
from pathlib import PurePosixPath

with tarfile.open(sys.argv[1], "r:gz") as archive:
    for member in archive.getmembers():
        name = member.name.removeprefix("./").rstrip("/")
        if name in {"", "."}:
            continue
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
            raise SystemExit(f"Unsafe path in upload archive: {member.name!r}")
        if not member.isfile():
            raise SystemExit(f"Unexpected non-file entry in upload archive: {member.name!r}")
PY

tar --extract --gzip --file="$plain_file" --directory="$staging_dir" --no-same-owner --no-same-permissions
find "$staging_dir" -mindepth 1 -maxdepth 1 -type f -exec mv --target-directory="$UPLOADS_TARGET" -- {} +
rm -rf "$staging_dir"
staging_dir=""
echo "Uploads restored. Verify file counts and hashes against the database before cutover."
