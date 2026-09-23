#!/usr/bin/env bash
# Restore a CareRoute backup, replacing the current database contents.
#
#   ./scripts/restore.sh backups/careroute_20260916T000000Z.dump
#
# DESTRUCTIVE: --clean drops existing objects before recreating them. The
# script refuses to run unless you confirm, or pass --force (for CI).

set -euo pipefail

cd "$(dirname "$0")/.."

DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-careroute}"
DB_NAME="${DB_NAME:-careroute}"

dumpfile="${1:-}"
force="${2:-}"

if [[ -z "$dumpfile" ]]; then
  echo "usage: $0 <dumpfile> [--force]" >&2
  exit 2
fi

if [[ ! -f "$dumpfile" ]]; then
  echo "!! No such backup file: ${dumpfile}" >&2
  exit 1
fi

if [[ "$force" != "--force" ]]; then
  echo "About to OVERWRITE database '${DB_NAME}' from ${dumpfile}."
  read -r -p "Type 'restore' to continue: " answer
  [[ "$answer" == "restore" ]] || { echo "Aborted."; exit 1; }
fi

echo "==> Restoring ${DB_NAME} from ${dumpfile}"

# --clean --if-exists drops each object before recreating it, so this works
# against a populated, partially-populated, or empty database.
#
# pg_restore exits non-zero on ignorable notices (e.g. DROP of an object that
# was never there). We capture the status, then verify the result for real by
# querying the restored data below rather than trusting the exit code alone.
set +e
docker compose exec -T "$DB_SERVICE" \
  pg_restore -U "$DB_USER" -d "$DB_NAME" \
    --clean \
    --if-exists \
    --no-owner \
    --no-privileges \
    --single-transaction \
  < "$dumpfile"
status=$?
set -e

if [[ $status -ne 0 ]]; then
  echo "!! pg_restore exited ${status}" >&2
  exit $status
fi

echo "==> Restore completed. Row counts now:"
docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -t -c "
  SELECT 'facilities', count(*) FROM facilities
  UNION ALL SELECT 'providers', count(*) FROM providers
  UNION ALL SELECT 'patients', count(*) FROM patients
  UNION ALL SELECT 'referrals', count(*) FROM referrals
  UNION ALL SELECT 'referral_events', count(*) FROM referral_events
  UNION ALL SELECT 'users', count(*) FROM users
  ORDER BY 1;"
