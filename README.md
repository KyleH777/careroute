# CareRoute — Containerized

FastAPI + Postgres 16, with JWT authentication and role-based access control,
Alembic migrations, a deterministic seed dataset, a tested backup/restore
drill, and a CI pipeline that lints, tests, scans and publishes the image.

Multi-stage Docker build: the build stage installs dependencies into a
virtualenv with compilers available, and the final stage copies only that
virtualenv plus application code into a clean `python:3.12-slim` image. No
compilers, no pip cache, no `.git` in the shipped image. Runs as a non-root
`app` user.

## Start everything

```bash
docker compose up --build
```

Startup is ordered on purpose: Postgres must report healthy, then a one-shot
`migrate` service runs `alembic upgrade head` and exits 0, and only then does
the api start. The api never serves traffic against an un-migrated schema.

Load the test dataset:

```bash
docker compose exec api python scripts/seed.py
```

Check it:

```bash
curl -s http://localhost:8000/stats
```

```json
{"facilities":5,"providers":24,"patients":120,"referrals":300,"referral_events":1002,"users":3}
```

## Stop

```bash
docker compose down
```

Data survives in a named volume. To destroy the database as well:

```bash
docker compose down -v
```

---

## Endpoints

| Path | Minimum role | Purpose |
|---|---|---|
| `GET /health` | public | Liveness. Deliberately does not touch the database |
| `GET /ready` | public | Readiness. Reports whether Postgres is reachable |
| `GET /stats` | public | Row counts per table — used by the restore drill |
| `POST /auth/token` | public | Exchange email + password for a bearer token |
| `GET /auth/me` | any | Who the presented token belongs to |
| `GET /referrals/worklist` | viewer | Open referrals, most urgent first, then oldest first |
| `GET /referrals/{id}` | viewer | A referral plus its full status-change history |
| `POST /patients` | clinician | Create a patient. 409 on duplicate `mrn` |
| `POST /referrals` | clinician | Submit a referral (starts in `draft`). 404 on missing patient/facility |
| `POST /referrals/{id}/status` | clinician | Transition status. 409 on an illegal transition |
| `POST /referrals/{id}/assign` | coordinator | Assign a provider. 409 on closed referral, specialty mismatch, or provider not accepting patients |

Interactive docs with a working **Authorize** button: <http://localhost:8000/docs>

`/health` avoids the database on purpose: a slow database should not cause the
orchestrator to kill an otherwise-healthy process. `/ready` is the one that
reports database trouble.

Assigning a provider does not itself write a `referral_event` —
`referral_events` is specifically a status-transition log, not a general
audit trail.

---

## Authentication

Staff accounts live in the `users` table (argon2id password hashes). Log in
with the OAuth2 password flow to get a short-lived HS256 JWT, then send it as
`Authorization: Bearer <token>`.

The seed script creates one demo login per role, all with password
`careroute-demo`:

| Email | Role | Can |
|---|---|---|
| `viewer@careroute.demo` | viewer | Read referrals and the worklist |
| `clinician@careroute.demo` | clinician | + create patients, submit referrals, change status |
| `coordinator@careroute.demo` | coordinator | + assign providers |

```bash
TOKEN=$(curl -s -X POST localhost:8000/auth/token \
  -d username=coordinator@careroute.demo -d password=careroute-demo \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/referrals/worklist?limit=3 -H "Authorization: Bearer $TOKEN"
```

Design decisions:

- **The audit trail is tamper-resistant.** `referral_events.actor` is the
  authenticated user's email. Request bodies carry no `actor` field, and one
  sent anyway is ignored, so nobody can record a change under someone else's
  name.
- **Revocation is immediate.** Each request re-reads the user's role and
  `is_active` from the database instead of trusting the token's claims, so a
  deactivated or demoted account loses access right away rather than when its
  token expires.
- **Login doesn't leak which emails exist.** Unknown email, wrong password and
  inactive account all return the same 401, and an unknown email still runs a
  full argon2 verify so response timing matches.
- **Production can't start with the dev secret.** With `APP_ENV` set to
  anything other than `local`/`test`, the app refuses to boot unless
  `JWT_SECRET` is set. The seed script likewise refuses to run, since its demo
  password is published right here.

---

## Schema changes

`app/models.py` is the single source of truth. Never edit the database by hand.

Change a model, then generate a migration:

```bash
docker compose run --rm --user root -v "$(pwd)/migrations:/home/app/migrations" migrate alembic revision --autogenerate -m "describe the change"
```

Review the generated file, then rebuild so the image carries it:

```bash
docker compose build
```

```bash
docker compose run --rm migrate alembic upgrade head
```

The rebuild is not optional. Migrations are baked into the image so the code
being deployed carries the schema it expects — which means a migration you
generated but did not rebuild will silently not run.

**Read the autogenerated file before applying it.** Alembic's autogenerate is
a starting point, not an oracle. It does not emit `DROP TYPE` for native enums,
which is why the initial migration's `downgrade()` drops `referral_status` and
`referral_priority` explicitly. Without that, a downgrade followed by an upgrade
fails with `DuplicateObject`.

Verify any new migration round-trips:

```bash
docker compose run --rm migrate alembic downgrade base && docker compose run --rm migrate alembic upgrade head
```

---

## Running tests

Tests run against their own ephemeral Postgres — never the dev database —
under a separate Compose project name so the two stacks never collide:

```bash
docker compose -p careroute-test -f docker-compose.test.yml run --build --rm test
docker compose -p careroute-test -f docker-compose.test.yml down -v
```

`--build` matters: `run` reuses an already-tagged image if one exists, so
without it a stale `careroute:test` image can silently run old code.

Coverage is reported at the end of every run.

Lint, format and type-check (pinned versions in `requirements-dev.txt`, config
in `pyproject.toml`):

```bash
ruff check . && ruff format --check . && mypy app
```

## Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request:

1. **Lint:** ruff, ruff format, and mypy
2. **Test:** the same `docker-compose.test.yml` suite as above, plus an Alembic
   `downgrade base` → `upgrade head` round-trip
3. **Image:** builds the runtime stage and scans it with Trivy, failing the
   build on any HIGH/CRITICAL vulnerability that has a fix available. On
   `main` only, it then pushes the image to GHCR as
   `ghcr.io/<owner>/<repo>:latest` and `:sha-<commit>`

Test-only dependencies (`pytest`, `httpx`) live in `requirements-dev.txt`
and a dedicated `test` Dockerfile stage — neither ships in the production
image built by `docker compose build`.

---

## Seed data

Deterministic: the RNG is seeded with 42, so every run produces identical data.
That is what makes the restore drill verifiable — hashes are expected to match
exactly.

```bash
docker compose exec api python scripts/seed.py
```

Idempotent — re-running is a no-op (apart from adding any missing demo
users). Refuses to run unless `APP_ENV` is `local` or `test`. To wipe and
reload:

```bash
docker compose exec api python scripts/seed.py --reset
```

---

## Backup and restore

Full step-by-step drill, with verified output: **[docs/BACKUP-RESTORE.md](docs/BACKUP-RESTORE.md)**

```bash
./scripts/backup.sh
```

```bash
./scripts/restore.sh backups/<file>.dump
```

```bash
./scripts/db_fingerprint.sh
```

The fingerprint hashes ordered table contents, so matching values before and
after a restore prove the same rows came back — not merely the same count.

`backups/` is git-ignored: dumps may contain real patient data and belong in
object storage, never in version control.

---

## Deploying to Azure

Setup for Azure Database for PostgreSQL Flexible Server, including free-tier
eligibility rules, TLS, migrations, and point-in-time restore:
**[docs/AZURE.md](docs/AZURE.md)**

Nothing there has been provisioned — those commands create billable resources
under your subscription.

The same image runs in both environments. `app/config.py` reads `DATABASE_URL`
from the environment, so dev and prod differ only by that variable.

---

## Live reload while you work

Mounts your local `app/` over the image's copy and restarts uvicorn on save.

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

---

## Other useful commands

Logs:

```bash
docker compose logs -f api
```

Status and health:

```bash
docker compose ps
```

Shell into the api container:

```bash
docker compose exec api /bin/bash
```

psql into the database:

```bash
docker compose exec db psql -U careroute -d careroute
```

Rebuild from scratch:

```bash
docker compose build --no-cache
```

---

## Verified

Everything above was executed against this stack, not assumed:

- Image builds clean; final image runs as non-root and contains only runtime artifacts
- Compose ordering works — api waits for migrations to complete successfully
- Migration applies, and round-trips through `downgrade base` → `upgrade head`
- Seed loads 1,451 rows across five tables and is idempotent on re-run
- Full disaster drill: fingerprint → backup → TRUNCATE everything → restore →
  all five table hashes identical, API functional, identity sequences correct
- Archive also restores into a brand-new empty database
- Referral write endpoints: full lifecycle (create patient → submit
  referral → assign provider → transition through to completed) exercised
  both by the pytest suite and manually against the live dev stack
- Business rules reject what they should: illegal status transitions,
  assigning a provider with the wrong specialty, assigning one that isn't
  accepting new patients, and assigning to a referral that isn't open —
  all return 409
- Auth against the live stack: no token → 401, bad password → 401, viewer
  write → 403, clinician assign → 403, coordinator assign → 200. A referral
  submitted with `"actor": "spoofed"` in the body recorded the clinician's
  real email in its history
- Adding `users` to an already-seeded database: migration applied, demo users
  added, and all five pre-existing table fingerprints unchanged
- Test suite: 63 tests, 99% line coverage of `app/`
