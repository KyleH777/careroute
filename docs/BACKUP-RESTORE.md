# Backup & Restore Drill

The recovery procedure for CareRoute's database, written as a drill you run
rather than a policy you file. Every step below was executed end to end against
the Compose stack; the sample output is real, not illustrative.

A backup you have never restored is not a backup. Run this drill on a schedule
and after any change to the schema or the Postgres version.

---

## What the three scripts do

| Script | Purpose |
|---|---|
| `scripts/backup.sh` | Writes a compressed `pg_dump` archive to `backups/` and verifies it is readable |
| `scripts/restore.sh` | Restores an archive over the current database (destructive) |
| `scripts/db_fingerprint.sh` | Hashes the ordered contents of every table |

The fingerprint is what makes the drill meaningful. Row counts only prove that
*something* came back; matching MD5 hashes of ordered table contents prove the
*same rows* came back.

`pg_dump` and `pg_restore` run inside the `db` container, so you do not need
Postgres client tools installed on your machine.

---

## The drill, step by step

### Step 0 — have a running stack with data

```bash
docker compose up -d
```

```bash
docker compose exec api python scripts/seed.py
```

### Step 1 — fingerprint the database before you touch anything

```bash
./scripts/db_fingerprint.sh | tee /tmp/fp_before.txt
```

```
facilities      87f47ee3bb656ded6328a2d864cb6ecd
providers       dd6db20213023d062a563377d7868a9e
patients        81df3387debbb23c240436a9d123fe4c
referrals       033b573d2604444f831cbf23a03592bf
referral_events 54620bae48a0d38564037cbf704f8c33
```

### Step 2 — take the backup

```bash
./scripts/backup.sh drill-demo
```

```
==> Backing up careroute to backups/drill-demo.dump
==> OK: backups/drill-demo.dump (36078 bytes), archive verified readable
```

Omit the label to get a UTC-timestamped filename instead.

The script does not just check that the file is non-empty — a `pg_dump` that
dies mid-stream still leaves bytes on disk. It runs `pg_restore --list` over
the result and deletes the file if it is not a readable archive.

### Step 3 — simulate the disaster

This is the step people skip. Do not skip it.

```bash
docker compose exec -T db psql -U careroute -d careroute -c "TRUNCATE referral_events, referrals, patients, providers, facilities RESTART IDENTITY CASCADE;"
```

Confirm the data is really gone:

```bash
curl -s http://localhost:8000/stats
```

```json
{"facilities":0,"providers":0,"patients":0,"referrals":0,"referral_events":0}
```

### Step 4 — restore

```bash
./scripts/restore.sh backups/drill-demo.dump
```

It prompts for confirmation — type `restore`. In CI, pass `--force` as a
second argument to skip the prompt.

```
==> Restoring careroute from backups/drill-demo.dump
==> Restore completed. Row counts now:
 facilities      |     5
 patients        |   120
 providers       |    24
 referral_events |  1002
 referrals       |   300
```

### Step 5 — prove the data is identical

```bash
./scripts/db_fingerprint.sh | tee /tmp/fp_after.txt && diff /tmp/fp_before.txt /tmp/fp_after.txt && echo "PASS: identical"
```

```
PASS: identical
```

### Step 6 — prove the application still works

A restore that satisfies the database but breaks the app is a failed restore.

```bash
curl -s http://localhost:8000/stats
```

```bash
curl -s "http://localhost:8000/referrals/worklist?limit=1"
```

Also confirm sequences survived, because a restore that leaves identity
sequences behind the data causes duplicate-key errors on the next insert:

```bash
docker compose exec -T db psql -U careroute -d careroute -c "INSERT INTO facilities (name, city, state, timezone, is_active) VALUES ('Seq Test','Boston','MA','UTC',true) RETURNING id;"
```

Verified: this returned `6`, correctly following the five restored rows.
Delete the test row afterwards.

---

## Drill result (last run)

| Check | Result |
|---|---|
| Archive readable by `pg_restore --list` | Pass |
| All data destroyed before restore | Pass — all counts 0 |
| Row counts after restore | Pass — 5 / 24 / 120 / 300 / 1002 |
| Table content hashes match pre-disaster | Pass — all five identical |
| API serves restored data | Pass |
| Identity sequences correct after restore | Pass — next id was 6 |

---

## Migration rollback round-trip

The schema has its own recovery path, tested the same way:

```bash
docker compose run --rm migrate alembic upgrade head
```

```bash
docker compose run --rm migrate alembic downgrade base
```

```bash
docker compose run --rm migrate alembic upgrade head
```

All three must succeed in sequence. This catches a specific trap: Alembic's
autogenerate does **not** emit `DROP TYPE` for native Postgres enums, so a
downgrade leaves `referral_status` and `referral_priority` behind and the next
upgrade dies with `DuplicateObject`. The initial migration's `downgrade()` drops
both types explicitly to close that gap. If you add an enum later, add its drop
too, then re-run this round-trip.

---

## Restoring into a fresh, empty database

The dump is taken with `--no-owner --no-privileges`, so it is portable across
environments where the admin role has a different name — notably Azure.

```bash
docker compose exec -T db createdb -U careroute careroute_verify
```

```bash
docker compose exec -T db pg_restore -U careroute -d careroute_verify --no-owner --no-privileges < backups/drill-demo.dump
```

This is the strongest form of the drill: it proves the archive can rebuild the
database from nothing, not merely overwrite a database that already has the
right shape.

---

## What this does not cover

Be honest about the boundaries of this procedure:

- **These are logical backups, not point-in-time recovery.** You can restore to
  the moment a dump was taken and no finer. In Azure, the platform's own
  automated backups provide PITR — see [AZURE.md](AZURE.md). Treat these dumps
  as a portable, provider-independent second line of defence, not a replacement.
- **`backups/` is git-ignored and local.** For anything real, ship archives off
  the machine that produced them — Azure Blob Storage with immutability, or
  equivalent. A backup on the same disk as the database is not a backup.
- **There is no automated schedule here.** Wire `backup.sh` to cron, a systemd
  timer, or a scheduled job, and alert on failure. An unmonitored backup job
  fails silently and you discover it during an incident.
- **Dev credentials are in `docker-compose.yml` deliberately.** They are local
  only. Never reuse them anywhere reachable from the internet.
