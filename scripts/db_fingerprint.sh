#!/usr/bin/env bash
# Print a deterministic fingerprint of the database contents.
#
# Row counts alone can't tell you whether a restore brought back the *same*
# rows. This hashes the ordered contents of every table, so a matching
# fingerprint before and after a restore is real evidence the data is intact.
#
#   ./scripts/db_fingerprint.sh

set -euo pipefail

cd "$(dirname "$0")/.."

DB_SERVICE="${DB_SERVICE:-db}"
DB_USER="${DB_USER:-careroute}"
DB_NAME="${DB_NAME:-careroute}"

docker compose exec -T "$DB_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -t -A -c "
  SELECT 'facilities      ' || md5(string_agg(t::text, '|' ORDER BY id)) FROM facilities t
  UNION ALL
  SELECT 'providers       ' || md5(string_agg(t::text, '|' ORDER BY id)) FROM providers t
  UNION ALL
  SELECT 'patients        ' || md5(string_agg(t::text, '|' ORDER BY id)) FROM patients t
  UNION ALL
  SELECT 'referrals       ' || md5(string_agg(t::text, '|' ORDER BY id)) FROM referrals t
  UNION ALL
  SELECT 'referral_events ' || md5(string_agg(t::text, '|' ORDER BY id)) FROM referral_events t
  UNION ALL
  SELECT 'users           ' || md5(string_agg(t::text, '|' ORDER BY id)) FROM users t;
"
