#!/usr/bin/env bash
# Take a compressed, timestamped logical backup of the CareRoute database.
#
#   ./scripts/backup.sh                 -> backups/careroute_<UTC timestamp>.dump
#   ./scripts/backup.sh my-label        -> backups/my-label.dump
#
# Uses pg_dump's custom format (-Fc): compressed, and restorable selectively
# with pg_restore (single table, schema-only, data-only) rather than being a
# single all-or-nothing SQL stream.
#
# pg_dump runs inside the db container, so no Postgres client is needed on the
# host. The dump streams over stdout to a file on the host.

set -euo pipefail

cd "$(dirname "$0")/.."

DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-careroute}"
DB_NAME="${DB_NAME:-careroute}"
BACKUP_DIR="${BACKUP_DIR:-backups}"

label="${1:-careroute_$(date -u +%Y%m%dT%H%M%SZ)}"
outfile="${BACKUP_DIR}/${label}.dump"

mkdir -p "$BACKUP_DIR"

echo "==> Backing up ${DB_NAME} to ${outfile}"

# --no-owner / --no-privileges keep the dump portable: it restores cleanly
# into Azure, where the admin role name differs from the local one.
docker compose exec -T "$DB_SERVICE" \
  pg_dump -U "$DB_USER" -d "$DB_NAME" \
    --format=custom \
    --no-owner \
    --no-privileges \
  > "$outfile"

# A pg_dump that fails mid-stream can still leave a non-empty file, so verify
# the archive is readable rather than just checking that bytes exist.
if ! docker compose exec -T "$DB_SERVICE" pg_restore --list < "$outfile" > /dev/null 2>&1; then
  echo "!! Backup at ${outfile} is not a readable pg_restore archive — deleting" >&2
  rm -f "$outfile"
  exit 1
fi

size=$(wc -c < "$outfile" | tr -d ' ')
echo "==> OK: ${outfile} (${size} bytes), archive verified readable"
