# What is this? 
CareRoute is a backend API for healthcare referral routing. When a doctor
refers a patient to a specialist, the referral has to be tracked, routed to
the right provider, and audited. I built it with FastAPI and Postgres, fully
containerized, and the focus was production practices: authentication with
role-based access, a tamper-resistant audit trail, versioned database
migrations, a verified backup-and-restore drill, a hardened container image,
and a CI pipeline that lints, tests, security-scans and publishes the image
on every push.

# CareRoute — Containerized

[![CI](https://github.com/KyleH777/careroute/actions/workflows/ci.yml/badge.svg)](https://github.com/KyleH777/careroute/actions/workflows/ci.yml)

**Live demo:** [https://careroute-api.yellowglacier-b6e91890.centralus.azurecontainerapps.io/docs](https://careroute-api.yellowglacier-b6e91890.centralus.azurecontainerapps.io/docs). Click **Authorize** and log in as
`viewer@careroute.demo` / `careroute-demo` (read-only). The API scales to zero
when idle, so the first request can take a few seconds.

FastAPI + Postgres 16, with JWT authentication and role-based access control,
Alembic migrations, a deterministic seed dataset, a tested backup/restore
drill, and a CI pipeline that lints, tests, scans and publishes the image.

Multi-stage Docker build on [Docker Hardened Images](https://dhi.io). The
build stage (`dhi.io/python:3.12-debian13-dev`) installs dependencies into a
virtualenv; the runtime stage (`dhi.io/python:3.12-debian13`) receives only
that virtualenv and the application code. The shipped image has **no shell,
no package manager and no compilers**, runs as non-root uid 65532, and its
code is root-owned, so the running process can't modify itself.

Pulling from `dhi.io` needs a (free) Docker account: run `docker login dhi.io`
once before the first build.

### Image security

| | `python:3.12-slim` (before) | Hardened image (now) |
|---|---|---|
| Size | 325 MB | 234 MB |
| Shell / package manager | yes / yes | no / no |
| CRITICAL / HIGH CVEs (Docker Scout, base VEX applied) | 0 / 2, no fix available | **0 / 0** |

The HIGH count comes from Docker Scout with the base image's VEX statements
applied. Those are Docker's published analysis of which CVEs actually affect the
hardened image. Without them, Scout lists six HIGHs in the base (zlib, expat,
libpython, and libraries vendored inside the base image's pip), all marked
`not_affected` by that VEX. To reproduce:

```bash
docker scout vex get dhi.io/python:3.12-debian13 --output dhi-vex.json
docker scout cves careroute:local --vex-location dhi-vex.json
```

Scout does **not** apply those statements to derived images on its own: a
registry scan of the published image still lists the six HIGHs. Pass the VEX
file explicitly, as above, to see the analyzed result.

## Start everything

```bash
docker compose up --build
```

Startup is ordered on purpose: Postgres must report healthy, then a one-shot
`db-roles` service creates the least-privilege database roles, then `migrate`
runs `alembic upgrade head` as the schema owner (`careroute_migrate`) and exits
0, and only then does the api start, as the DML-only `careroute_app`. The api
never serves traffic against an un-migrated schema, and can't change the schema
itself ([ADR-0010](docs/adr/0010-per-workload-identities-and-db-roles.md)). The
same split runs in the test stack and CI, where `tests/test_db_roles.py` fails
the build if a migration leaves the app without a grant.

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
| `GET /ready` | public | Readiness. 503 when Postgres is unreachable |
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
reports database trouble, as a **503** so load balancers stop routing to it.

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
  anything other than `local`/`dev`/`test`, the app refuses to boot unless
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
users). Refuses to run unless `APP_ENV` is `local`, `dev` or `test`. To wipe and
reload (runs as the schema owner, because only it may truncate; ADR-0010):

```bash
docker compose run --rm migrate python scripts/seed.py --reset
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

## Operations

- **[On-call runbook](docs/RUNBOOK.md)**: symptoms, diagnosis and fixes for
  database outages, failed starts, auth failures, rollbacks, restores and red
  CI. The Compose procedures were run against this stack; of the Azure ones, the
  log read, in-VNet database queries and role rollout were run live, and the rest are syntax-checked.
- **[Architecture decisions](docs/adr/README.md)**: why it's built this way,
  one short record per decision (probes, auth, audit, image, state, network,
  secrets, demo access).
- **[Incident response](docs/INCIDENT-RESPONSE.md)**: severity levels, roles,
  communication, the security/PHI-exposure path, known gaps, and a
  post-incident review template.

---

## Infrastructure as code (Terraform)

Terraform state lives in Azure Storage, in its own resource group so tearing
down the app can never delete it. The storage is bootstrapped with the Azure
CLI, because Terraform can't create the storage that holds its own state:

```bash
az login
./infra/backend-setup/setup-backend.sh     # shows the plan and asks before creating anything
cd infra && terraform init -backend-config=backend.hcl
```

The state storage account uses Entra ID auth only (storage keys disabled),
HTTPS/TLS 1.2, no public access, blob versioning with 30-day soft delete, and a
delete lock.

`infra/` declares the whole Azure deployment, all in centralus: the API on
Container Apps, plus migrate and seed jobs; Postgres 16 on a private VNet with no
public endpoint; Key Vault holding Terraform-generated secrets, read through a
managed identity; and Log Analytics. Details in
**[docs/AZURE.md](docs/AZURE.md)**. Rationale in ADRs
[0006](docs/adr/0006-terraform-state-backend.md),
[0007](docs/adr/0007-private-postgres-in-centralus.md) and
[0008](docs/adr/0008-secrets-generated-into-key-vault.md).

---

## Deploying to Azure

The [live demo](#careroute--containerized) runs on Azure and is deployed and
changed only through Terraform. **[docs/AZURE.md](docs/AZURE.md)** covers the
architecture, deploying a new image (migrate first, then roll the app), logs,
secret rotation, point-in-time restore, cost and teardown. Applying the
Terraform in your own subscription creates billable resources (see AZURE.md →
Cost).

The same image runs in both environments. `app/config.py` reads `DATABASE_URL`
from the environment, so dev and prod differ only by that variable. In Azure the
value comes from Key Vault, not from a committed file or a hand-set app setting.

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

There is no shell in the api container, on purpose. Run Python directly:

```bash
docker compose exec api python -c "import app.main; print('ok')"
```

For interactive debugging, `docker debug careroute-api` attaches a toolbox
shell without adding one to the image.

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

- Image builds clean; final image runs as uid 65532 with no shell (`exec api id`
  fails: no such executable) and contains only runtime artifacts
- 0 CRITICAL / 0 HIGH in Docker Scout with the base VEX applied; Trivy finds 0
  fixable HIGH/CRITICAL
- Dev overlay (`APP_ENV=dev`) boots with the default JWT secret; any other
  non-dev `APP_ENV` refuses to
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
