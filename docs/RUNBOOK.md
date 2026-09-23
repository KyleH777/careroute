# On-Call Runbook

What to check, and what to run, when CareRoute misbehaves.

**What's been verified against the live stack:** the database-outage
symptoms and recovery, the missing-`JWT_SECRET` startup refusal, user
lockout, secret rotation, the audit query, and the diagnostic commands. The
restore is verified by the drill in BACKUP-RESTORE.md. **Not exercised
here:** the schema-downgrade rollback (destructive), the Azure steps, and the
disk-cleanup commands. Rehearse those on a copy before relying on them.

For declaring an incident, severity, communication and follow-up, see
**[INCIDENT-RESPONSE.md](INCIDENT-RESPONSE.md)**. This runbook is the "how do I
fix it" half; that doc is the "how do we run the incident" half.

Commands assume the Compose stack from the repo root. For Azure, the same
checks apply against the deployed URL; `docker compose` steps become their
Azure equivalents (see [AZURE.md](AZURE.md)).

---

## First five minutes

Run these in order. Together they tell you which section below to go to.

```bash
docker compose ps                                   # 1. what's running, what's healthy
curl -s -w ' [%{http_code}]\n' localhost:8000/health  # 2. is the process alive?
curl -s -w ' [%{http_code}]\n' localhost:8000/ready   # 3. can it reach the database?
docker compose logs api --since 15m | tail -50      # 4. what is it saying?
docker compose logs migrate                         # 5. did the last migration succeed?
```

| `/health` | `/ready` | Most likely | Go to |
|---|---|---|---|
| no response | no response | api container down or not started | [API won't start](#api-wont-start) |
| 200 | **503** | database unreachable | [Database unreachable](#database-unreachable) |
| 200 | 200 | app is up; problem is narrower | [Everything is up but requests fail](#everything-is-up-but-requests-fail) |

### The two probes, and why they differ

- **`/health` (liveness)** never touches the database. The container
  `HEALTHCHECK` uses it, so a database outage does **not** make Docker mark the
  api unhealthy or restart it. Restarting a healthy process wouldn't fix a
  database outage anyway.
- **`/ready` (readiness)** runs `SELECT 1` and returns **503** when the database
  is unreachable. This is the one a load balancer should use to stop sending
  traffic. The underlying error is logged, not returned, because the endpoint
  is public.

So **"container healthy" does not mean "service working."** Always check
`/ready`.

---

## Database unreachable

**Symptoms** (observed with the database stopped):

- `/health` → 200, `/ready` → **503** `{"status":"degraded","database":"unreachable"}`
- Every authenticated endpoint **and login** → **500**
- `docker compose ps` still shows the api as **healthy** (see above)
- api logs: `readiness check failed: database unreachable: (psycopg.OperationalError) ...`

**Diagnose:**

```bash
docker compose ps db
docker compose logs db --since 15m | tail -30
docker compose exec db pg_isready -U careroute -d careroute
```

**Fix:**

| Cause | Action |
|---|---|
| db container stopped/crashed | `docker compose start db` |
| db container restarting in a loop | Read `docker compose logs db`. Often disk full (below) or a corrupted data directory ([Data loss](#data-loss-or-corruption)) |
| Disk full | `docker system df`, then free space (see [Disk full](#disk-full)) |
| Azure: connection refused/timeout | Check the server is running and the firewall rule allows the app's outbound IP (AZURE.md → Network access) |
| Azure: `SSL`/`sslmode` errors | `DATABASE_URL` must end in `?sslmode=require` |

**Recovery is automatic.** You do **not** need to restart the api once the
database is back. `pool_pre_ping` discards dead connections, and `/ready`
returned to 200 on the next request in testing.

**Verify:**

```bash
curl -s -w ' [%{http_code}]\n' localhost:8000/ready     # expect 200, "reachable"
```

---

## API won't start

The api only starts after `migrate` **exits 0**, so check migrate first.

```bash
docker compose ps -a                 # look at migrate's exit code
docker compose logs migrate
docker compose logs api | tail -40
```

### `migrate` exited non-zero → api never started

This is the ordering doing its job: the api won't serve traffic against a
half-migrated schema. Read the migrate log:

| Error in log | Meaning | Action |
|---|---|---|
| `OperationalError ... could not connect` / `Name or service not known` | db not reachable | [Database unreachable](#database-unreachable) |
| `DuplicateObject: type "..." already exists` | A previous downgrade left an enum type behind | Check the migration's `downgrade()` has an explicit `DROP TYPE`; see README → Schema changes |
| `Can't locate revision identified by '...'` | Database is at a revision this image doesn't know (e.g. rolled the image back past a migration) | Deploy the image that contains that revision, or downgrade the DB with the newer image first ([Bad deploy](#bad-deploy--rollback)) |
| Any SQL error mid-migration | The migration itself is broken | Postgres DDL is transactional, so the failed migration rolled back. Fix it, rebuild, redeploy |

### api container exits immediately

```bash
docker compose logs api | grep -E "Error|JWT_SECRET" | head
```

| Error | Meaning | Action |
|---|---|---|
| `JWT_SECRET must be set when APP_ENV='production'` | Deliberate refusal: a non-dev environment has no real signing secret | Set `JWT_SECRET` (AZURE.md → JWT signing secret) and restart. **Do not** "fix" it by setting `APP_ENV=local` in production |
| `ValidationError ... Settings` (other) | Malformed environment variable | Compare against `.env.example` |
| `Address already in use` | Port 8000 taken on the host | `lsof -i :8000`, stop the other process |

---

## Everything is up but requests fail

`/health` and `/ready` are both 200.

| Status | Meaning | Check |
|---|---|---|
| **401** on every request | Tokens are being rejected | Did `JWT_SECRET` change? A rotation invalidates **every** outstanding token by design; users must log in again. Otherwise check the client is sending `Authorization: Bearer <token>` |
| **401** for one user | Account deactivated, token expired (60 min), or wrong password | `docker compose exec db psql -U careroute -d careroute -c "select email, role, is_active from users where email='<email>';"` |
| **403** | Authenticated, wrong role | Working as designed. See README → Authentication for the role matrix |
| **409** | A business rule rejected it | Working as designed. The `detail` field says which rule (illegal transition, specialty mismatch, provider not accepting, referral not open) |
| **422** | Request body failed validation | Client bug. The response lists the offending fields |
| **500** | Unhandled error | `docker compose logs api --since 15m \| grep -B2 -A20 Traceback` |

Quick end-to-end check with a demo login (dev only):

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/token -d username=viewer@careroute.demo -d password=careroute-demo \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
curl -s -w ' [%{http_code}]\n' "localhost:8000/referrals/worklist?limit=1" -H "Authorization: Bearer $TOKEN"
```

---

## Security actions

### Lock out a user immediately

Every request re-reads the user from the database, so this takes effect on
their **next request**. No need to wait for their token to expire.

```bash
docker compose exec db psql -U careroute -d careroute \
  -c "update users set is_active = false where email = '<email>' returning email, is_active;"
```

Re-enable with `is_active = true`.

### Invalidate everyone's tokens (suspected `JWT_SECRET` leak)

Rotate the secret. Every existing token instantly fails signature checks.

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set it as `JWT_SECRET` in the environment (Azure: App Setting / Key Vault) and
restart the api. With Compose:

```bash
JWT_SECRET='<new-secret>' docker compose up -d api
```

Verified: after rotation an old token gets 401 and a fresh login gets 200. Expect a burst of 401s as clients re-authenticate. That's
the rotation working.

### See what an account did

`referral_events.actor` is the authenticated user's email, taken from the
token and never from the request body.

```bash
docker compose exec db psql -U careroute -d careroute -c "
  select occurred_at, referral_id, from_status, to_status, note
  from referral_events where actor = '<email>'
  order by occurred_at desc limit 50;"
```

**Know the gaps before you rely on this:** only status changes are logged.
**Reads are not logged** (you cannot tell which patients an account viewed),
and **provider assignment is not logged**. See INCIDENT-RESPONSE.md →
Known limitations.

---

## Bad deploy / rollback

CI publishes every `main` commit as `ghcr.io/kyleh777/careroute:sha-<commit>`
alongside `:latest`, so every previous build is still pullable.

**1. Decide whether the database schema changed** between the good and bad
versions:

```bash
git diff <good-sha> <bad-sha> --stat -- migrations/versions/
```

**2a. No migration changed:** redeploy the previous image. Nothing else needed.

```bash
docker pull ghcr.io/kyleh777/careroute:sha-<good-sha>
# Compose (local): check out the good commit and rebuild
git checkout <good-sha> && docker compose up --build -d
```

**2b. A migration changed:** roll the **schema** back first, using the **new**
image (only it contains the downgrade code), then deploy the old image.

```bash
./scripts/backup.sh pre-rollback                                   # always, first
docker compose run --rm migrate alembic current                   # where are we?
docker compose run --rm migrate alembic downgrade <good-revision>  # e.g. 0f4937d2a980
```

> ⚠️ **A downgrade can destroy data.** Downgrading past `add users table`
> **drops the `users` table**: every account is gone. Read the migration's
> `downgrade()` before running it. If data loss is unacceptable, roll
> **forward** with a fix instead.

**Verify:** `alembic current` shows the expected revision, `/ready` is 200,
and the smoke check in [Everything is up](#everything-is-up-but-requests-fail) passes.

---

## Data loss or corruption

Wrong data, missing rows, a bad manual `UPDATE`. Full procedure with verified
output: **[BACKUP-RESTORE.md](BACKUP-RESTORE.md)**. The short version:

```bash
./scripts/backup.sh pre-restore-$(date -u +%Y%m%dT%H%M%SZ)   # 1. snapshot the CURRENT state first
ls -lt backups/                                           # 2. pick the restore point
./scripts/restore.sh backups/<file>.dump                  # 3. type 'restore' to confirm
./scripts/db_fingerprint.sh                               # 4. compare with a known-good fingerprint
```

Step 1 is not optional: the current state is evidence, and it's your way back
if you pick the wrong restore point.

- Restore replaces **everything** since the backup. Anything written after it
  is lost unless you replay it.
- **Azure:** prefer point-in-time restore to a *new* server (AZURE.md →
  Backups on Azure). It doesn't overwrite the live database, and it can recover
  to the minute before the bad change.

---

## Disk full

```bash
docker system df                       # what's using space
docker compose exec db du -sh /var/lib/postgresql/data   # database size
du -sh backups/
```

Safe to reclaim: old images (`docker image prune`), build cache
(`docker builder prune`), and old dumps in `backups/` **after** copying them to
object storage.

**Never** run `docker volume prune` or `docker compose down -v`: the
`careroute-pgdata` volume **is** the database.

---

## CI is red

| Failing job | Meaning | Action |
|---|---|---|
| Lint & type-check | ruff/mypy found an issue | Run `ruff check . && ruff format --check . && mypy app` locally |
| Tests & migrations → dhi.io login | `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN` secrets missing or token expired | Regenerate the Docker Hub token, `gh secret set DOCKERHUB_TOKEN -R KyleH777/careroute` |
| Tests & migrations → pytest | A test failed | Run the test stack locally (README → Running tests) |
| Build, scan & publish → Trivy | A **fixable** HIGH/CRITICAL CVE is in the image | The log names the package and fixed version. Bump it in `requirements.txt`, or rebuild to pick up a patched base image |

A red Trivy job means **nothing was published**. The last good image is still
`:latest`, so production is unaffected.

---

## Reference

| Thing | Where |
|---|---|
| Logs | `docker compose logs -f api` |
| psql | `docker compose exec db psql -U careroute -d careroute` |
| Python in the api container (no shell, by design) | `docker compose exec api python -c "..."` |
| Interactive debugging | `docker debug careroute-api` |
| Current schema revision | `docker compose run --rm migrate alembic current` |
| Row counts | `curl -s localhost:8000/stats` |
| Published images | `ghcr.io/kyleh777/careroute:latest`, `:sha-<commit>` |
