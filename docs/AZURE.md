# Azure deployment (Terraform)

How CareRoute runs on Azure, and how to operate it. `infra/` is the source of
truth: if this page and the Terraform disagree, the Terraform wins and this page
has a bug.

> **What's live.** CareRoute has run on Azure since 2026-09-24, in
> **centralus**, built entirely by Terraform (27 resources in state). The public
> API is
> [careroute-api.yellowglacier-b6e91890.centralus.azurecontainerapps.io](https://careroute-api.yellowglacier-b6e91890.centralus.azurecontainerapps.io/docs).
> Resource names carry a random suffix, so read them from Terraform rather than
> copying them from docs:
>
> ```bash
> cd infra && terraform output
> ```
>
> `api_url`, `resource_group`, `key_vault_name`, `postgres_fqdn` and `jobs` are
> the outputs the commands below rely on.

**How the commands on this page were checked:** every `az` and `terraform`
command was checked against `--help` and `infra/*.tf` on 2026-09-25. Three
paths were then **run against the live deployment**: console logs, the in-VNet
query, and `alembic current`. Rotation, restore, deploys and downgrades were
not run, to avoid cost and disruption to the public demo. Treat those as
reviewed, not rehearsed.

---

## Architecture

| Resource | Name | Purpose |
|---|---|---|
| Resource group | `careroute-rg` (centralus) | Everything below |
| Resource group | `careroute-env-infra-rg` (centralus) | Created and managed by Azure for the Container Apps environment's plumbing. Don't edit it by hand |
| Resource group | `careroute-tfstate-rg` (eastus) | Terraform state storage. Created by `setup-backend.sh`, **not** by Terraform ([ADR-0006](adr/0006-terraform-state-backend.md)) |
| Virtual network | `careroute-vnet` 10.20.0.0/16 | Private network for the app and the database |
| Subnet | `snet-apps` 10.20.0.0/23 | Delegated to the Container Apps environment |
| Subnet | `snet-postgres` 10.20.2.0/24 | Delegated to Postgres Flexible Server |
| Private DNS zone | `careroute.postgres.database.azure.com` + VNet link | Resolves the database's private hostname inside the VNet |
| Postgres Flexible Server | `careroute-pg-<suffix>` | Postgres 16, B1ms, 32 GiB, 7-day backups, admin login `careroute_admin` |
| Database | `careroute` | The application database |
| Key Vault | `kv-careroute-<suffix>` | Every secret, RBAC mode, 7-day soft delete |
| Managed identities | `careroute-app-id` (API), `careroute-migrate-id`, `careroute-seed-id`, `careroute-dbbootstrap-id` | One per workload ([ADR-0010](adr/0010-per-workload-identities-and-db-roles.md)) |
| Role assignments | Key Vault Secrets Officer (whoever runs Terraform, vault-wide); Key Vault Secrets User **per secret** for each workload identity | Write vs. read access. Each workload reads only its own secrets (see [Secrets and rotation](#secrets-and-rotation)) |
| Log Analytics workspace | `careroute-logs` | Container logs, 30-day retention, 0.5 GB/day ingestion cap |
| Container Apps environment | `careroute-env` | Consumption workload profile, VNet-integrated |
| Container App | `careroute-api` | The API. External ingress on port 8000, 0-2 replicas, liveness `/health`, readiness `/ready` |
| Container Apps Job | `careroute-migrate` | `alembic upgrade head`, manual trigger |
| Container Apps Job | `careroute-seed` | `python scripts/seed.py --demo-deployment`, manual trigger |
| Resource group | `careroute-ci-rg` (centralus) | Holds only the CI deploy identity. Applied by a human from `infra/ci/`; CI has no role here ([ADR-0011](adr/0011-ci-deploys-via-terraform.md)) |
| Managed identity | `careroute-ci-id` | What GitHub Actions deploys as (OIDC, `production` environment only) |
| Container Apps Job | `careroute-db-bootstrap` | `python scripts/db_roles.py` as the server admin: creates and maintains the database roles, manual trigger |

**Network.** Postgres is VNet-injected into `snet-postgres` with
`public_network_access_enabled = false`. It has no public endpoint, so there
are **no firewall rules** to open, audit or get wrong. Only workloads inside
`careroute-vnet` can reach it, which means no laptop `psql` (see
[Querying the database from inside the VNet](#querying-the-database-from-inside-the-vnet)).
TLS is required, and `DATABASE_URL` ends in `?sslmode=require`. Why:
[ADR-0007](adr/0007-private-postgres-in-centralus.md).

**Region.** The app is in **centralus** because this subscription can't create
Postgres Flexible Server in eastus, eastus2 or westus2. The state storage
account predates that finding and stays in eastus. It holds only the state
file, so the cross-region hop doesn't matter.

**Secrets.** Terraform's `random_password` generates every secret and writes it
to Key Vault. Each workload reads only its own secrets, through its own
identity, using versionless Key Vault references. No human types, sees or
pastes a production secret. Why:
[ADR-0008](adr/0008-secrets-generated-into-key-vault.md) and
[ADR-0010](adr/0010-per-workload-identities-and-db-roles.md). The same values are
also in Terraform state, which is why the state backend is locked down
([ADR-0006](adr/0006-terraform-state-backend.md)).

**Database roles.** Nothing that runs day to day connects as the server admin
([ADR-0010](adr/0010-per-workload-identities-and-db-roles.md)):

| Postgres role | Can | Used by | Key Vault secret | Identity |
|---|---|---|---|---|
| `careroute_app` | SELECT/INSERT/UPDATE/DELETE on app tables. No DDL, no TRUNCATE | API, seed job | `database-url` | `careroute-app-id` (API), `careroute-seed-id` (seed) |
| `careroute_migrate` | Owns the schema: all DDL | migrate job | `database-url-migrate` | `careroute-migrate-id` |
| `careroute_admin` (server admin) | Everything | **only** the db-bootstrap job | `database-url-admin` | `careroute-dbbootstrap-id` |

---

## First-time deployment

You only need this to build the stack in a new subscription. It's already live
in the current one.

**1. Bootstrap the state backend** (once per subscription, Azure CLI by
design; see [ADR-0006](adr/0006-terraform-state-backend.md)):

```bash
az login
```

```bash
./infra/backend-setup/setup-backend.sh
```

**2. Create the CI deploy identity** (its own root, applied only by a
human, [ADR-0011](adr/0011-ci-deploys-via-terraform.md)). The main config
refers to it, so it comes first:

```bash
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

```bash
cd infra/ci && terraform init -backend-config=../backend.hcl && terraform apply
```

**3. Apply the main config.** The image variables are required: name the
`sha-` tag to start with. `TF_VAR_operator_object_id` is you, the human who
keeps Key Vault Secrets Officer:

```bash
cd infra && terraform init -backend-config=backend.hcl
```

```bash
export TF_VAR_operator_object_id=$(az ad signed-in-user show --query id -o tsv)
```

```bash
export TF_VAR_alert_email=<owner's alert address>   # same value as the TF_VAR_ALERT_EMAIL GitHub secret
```

```bash
terraform apply -var app_image=ghcr.io/kyleh777/careroute:sha-<tag> -var migrate_image=ghcr.io/kyleh777/careroute:sha-<tag>
```

**4. Don't write plan files.** They embed every secret. `*.tfplan` is
git-ignored, but that only keeps it out of git, not off your disk. Review the
plan `terraform apply` shows before you confirm.

**5. Create the database roles, then migrate, then seed.** Terraform never runs
the jobs itself. First the roles:

```bash
az containerapp job start -g careroute-rg -n careroute-db-bootstrap
```

On a fresh database the API is up before any tables exist. `/ready` still returns 200
(it only checks that the database is reachable), but every data request fails
until the migration runs ([ADR-0001](adr/0001-one-shot-migration-before-api.md)).

```bash
az containerapp job start -g careroute-rg -n careroute-migrate
```

```bash
az containerapp job execution list -g careroute-rg -n careroute-migrate -o table
```

Wait for the execution to show `Succeeded`, then seed the read-only demo
([ADR-0009](adr/0009-read-only-public-demo.md)):

```bash
az containerapp job start -g careroute-rg -n careroute-seed
```

---

## Deploying a new image

**CI does this on every push to `main`** ([ADR-0011](adr/0011-ci-deploys-via-terraform.md)).
After lint, tests and the image publish pass, the `deploy` job in
`.github/workflows/ci.yml` signs in to Azure over OIDC (no stored credential)
as `careroute-ci-id` and runs `.github/scripts/deploy.sh` in
[ADR-0001](adr/0001-one-shot-migration-before-api.md) order:

1. **Stage 1:** `terraform apply` with `migrate_image` = the new tag and
   `app_image` = the live one. Only the migrate job changes.
2. **Migrate:** start `careroute-migrate` and wait. Anything but `Succeeded`
   fails the run here. The app was never touched, so the previous revision
   keeps serving.
3. **Stage 2:** `terraform apply` with both images = the new tag. The API,
   seed and db-bootstrap move. Single revision mode keeps the old revision
   serving until the new one passes readiness.
4. **Smoke:** `/ready` 200, both images are the new tag, and the active
   revision runs it.

Deploys run one at a time (`deploy-production` concurrency), and a newer push
never cancels a running one. Watch them in the Actions tab, or:

```bash
gh run list -R KyleH777/careroute --workflow CI --limit 5
```

**Redeploy an existing tag** (rollback when the schema didn't change; see
RUNBOOK → Bad deploy):

```bash
gh workflow run ci.yml --ref main -R KyleH777/careroute -f image_tag=sha-<good>
```

**Drill** (proves a failed migration stops the deploy; last run 2026-09-28,
run 36374139943):

```bash
gh workflow run ci.yml --ref main -R KyleH777/careroute -f simulate_migration_failure=true
```

### Running Terraform by hand

For infra changes, rotations and teardown. The image variables have no
default, so every apply must say which images to keep. Take them from the live
state, so a manual apply never moves images:

```bash
cd infra && export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv) TF_VAR_operator_object_id=$(az ad signed-in-user show --query id -o tsv) TF_VAR_alert_email=<owner's alert address>
```

(The alert address must match the `TF_VAR_ALERT_EMAIL` GitHub environment
secret, or your apply and the next CI deploy will flip it back and forth.)

```bash
TF_IMAGES=(-var "app_image=$(terraform output -raw app_image)" -var "migrate_image=$(terraform output -raw migrate_image)")
```

```bash
terraform apply "${TF_IMAGES[@]}"
```

Don't apply while a CI deploy is running: its state lock will stop you, and
stale `TF_IMAGES` would undo its stage 2. Commit any infra change to `main`
too, or the next CI deploy will revert it.

**A manual deploy** (CI unavailable) is the same order by hand: stage 1 with
`-var migrate_image=<new>` and the live `app_image`, run the migrate job and
check it `Succeeded`, then stage 2 with both set to `<new>`.

### Job environments

A job **command override** replaces the job's whole container definition, so
the command and environment must be passed again. Without them the job starts
the image's default command, which is the API server, with no database URL.
An override can only reference secrets that are defined on that job. Set the
environments once per shell:

```bash
MIGRATE_ENV=(APP_ENV=production PYTHONUNBUFFERED=1 DATABASE_URL=secretref:database-url-migrate JWT_SECRET=secretref:jwt-secret)
```

```bash
READ_ENV=(APP_ENV=production PYTHONUNBUFFERED=1 DATABASE_URL=secretref:database-url)
```

`MIGRATE_ENV` is for the migrate job (schema owner). `READ_ENV` is for the
seed job (DML-only app role), which is the one to use for queries.

---

## Migrations and seeding

All jobs run the deployed image, each with its own identity and database role.

| | `careroute-db-bootstrap` | `careroute-migrate` | `careroute-seed` |
|---|---|---|---|
| Command | `python scripts/db_roles.py` | `alembic upgrade head` | `python scripts/seed.py --demo-deployment` |
| Connects as | server admin | `careroute_migrate` | `careroute_app` |
| Trigger | Manual | Manual | Manual |
| Timeout | 300 s | 600 s | 600 s |
| Retries | 0 | **0**: a failed migration needs a human, not a retry | 0 |
| Secrets | `database-url-admin`, `db-migrate-password`, `db-app-password` | `database-url-migrate`, `jwt-secret` | `database-url`, `jwt-secret`, both private demo passwords |

`db-bootstrap` is safe to re-run at any time. It creates missing roles,
re-syncs their passwords, hands any stray objects to `careroute_migrate` and
re-applies grants. Run it after a password rotation, and whenever the API logs
`permission denied for table ...`.

To review a migration's SQL before it runs in production, render it against
the **local** stack. The SQL is the same, and no production credentials are
involved:

```bash
docker compose run --rm migrate alembic upgrade head --sql
```

---

## Logs, metrics and alerts

### What the API logs

Every response carries an **`X-Request-ID`** header (a well-formed one sent by
the client is kept, otherwise a uuid4 is generated). Ask anyone reporting a
problem for it. The API writes JSON, one object per line
([ADR-0012](adr/0012-alerting-without-availability-probes.md)):

| `event` | Logger | Fields |
|---|---|---|
| `request` | `careroute.access` | `request_id`, `method`, `route` (template, e.g. `/referrals/{referral_id}`), `path` (no query string), `status`, `duration_ms`. Exactly one per request |
| `audit` | `careroute.audit` | `request_id`, `action` (`referral.created`, `referral.status_changed`), `actor`, `referral_id`, `from_status`, `to_status`. No notes or reasons |
| (none) | `careroute.error` etc. | `msg`, `request_id`, `exc` (traceback) for unhandled errors, which still return a JSON 500 with the header |

### Where logs live

Live output from a running replica:

```bash
az containerapp logs show -g careroute-rg -n careroute-api --type console --tail 100
```

Add `--follow` to stream. Use `--type system` for platform events such as
image pulls, probe failures, Key Vault reference errors and restarts.
`logs show` needs a **running replica**. If the API has scaled to zero, it
starts one, which costs a few seconds of compute and shows only that fresh
replica's output.

A job's output (defaults to its latest execution):

```bash
az containerapp job logs show -g careroute-rg -n careroute-migrate --container migrate
```

**Everything else is in Log Analytics** (workspace `careroute-logs`, table
`ContainerAppConsoleLogs_CL`, JSON in `Log_s`). It outlives revisions and
replicas: on 2026-09-28 it still returned lines from three revisions that no
longer existed. Parse the JSON with `parse_json(Log_s)`. Ready-made queries are
in RUNBOOK → Log queries. From the CLI:

```bash
WS=$(az monitor log-analytics workspace show -g careroute-rg -n careroute-logs --query customerId -o tsv)
```

```bash
az monitor log-analytics query -w $WS --analytics-query "ContainerAppConsoleLogs_CL | extend e = parse_json(Log_s) | where tostring(e.request_id) == '<id>' | project TimeGenerated, RevisionName_s, Log_s" -o table
```

Limits:
- **Retention is 90 days** (set in `infra/containerapps.tf`). Export anything
  you need as evidence beyond that.
- Ingestion is capped at **0.5 GB/day** as a cost guard. Past the cap, logs
  **stop being collected** until the next day, and so do the two log-based
  alerts below. A noisy failure can hide what comes after it.

### Client IPs behind ingress

Container Apps ingress (Envoy) appends the connecting client's IP to
`X-Forwarded-For`. The API is deployed with `TRUSTED_PROXY_HOPS=1`, so it uses
only that rightmost entry for login rate limiting and the login-attempt log;
anything a client forges sits to its left and is ignored
([ADR-0013](adr/0013-login-rate-limiting.md); verified live 2026-09-29).
Change this only if another proxy is put in front of ingress.

### Metrics

Prometheus metrics are served on **port 9000 only**, by a separate listener.
Ingress maps only 8000, so `<api_url>/metrics` is a 404 and 9000 isn't
reachable from outside. Series: `careroute_http_requests_total` and
`careroute_http_request_duration_seconds` (by `method`, `route`, `status`),
`careroute_db_pool_size`, `_checked_out` and `_overflow`. To read them, run
inside the replica (`script` supplies the terminal `az containerapp exec`
insists on):

```bash
script -q /dev/null az containerapp exec -g careroute-rg -n careroute-api --command "python -c \"import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:9000').read().decode())\""
```

Locally, Compose publishes it at `http://localhost:9000`.

### Alerts

All three email the owner through action group `careroute-owner` (the address
comes from `TF_VAR_alert_email`: the GitHub environment secret, or your shell
for manual applies). Why these and not an availability probe:
[ADR-0012](adr/0012-alerting-without-availability-probes.md).

| Alert | Signal | Fires when | Severity |
|---|---|---|---|
| `careroute-db-down` | Postgres metric `is_db_alive` | < 1 over 5 min. Works with zero traffic | 0 |
| `careroute-ready-failing` | Log search on `event=request` | any `/ready` 503 in 5 min | 1 |
| `careroute-5xx-spike` | Log search on `event=request` | ≥ 5 responses with status ≥ 500 in 5 min | 2 |

They resolve automatically, and you get a second email when they do.

**Drill, 2026-09-28** (Postgres stopped): `5xx-spike` fired at 12:48,
`ready-failing` at 12:50 and `db-down` at 12:51, 1-4 minutes after the server
stopped. All three resolved on their own after it was started again. Azure ran
the action group for all six transitions; only some emails reached the inbox,
so check Junk/Other and consider adding a second receiver (Azure mobile app
push). The drill also found that `/ready` hung for minutes instead of 503ing
fast. Fixed with a 5 s connect timeout (`DB_CONNECT_TIMEOUT`). What to do when one fires: RUNBOOK
→ When an alert fires. Cost: about $2-4/month.

## Querying the database from inside the VNet

A laptop can't reach the database: it has no public endpoint, by design. To
run a one-off query, start a job with a **command override**. It runs inside
the VNet. The image has Python, SQLAlchemy and psycopg, but no shell and no
`psql`.

Which job decides which role you connect as:

| For | Job | Env | Role |
|---|---|---|---|
| Reads and data fixes (account lookup, lockout, audit queries) | `careroute-seed`, container `seed` | `READ_ENV` | `careroute_app` |
| Alembic (`current`, `downgrade`) | `careroute-migrate`, container `migrate` | `MIGRATE_ENV` | `careroute_migrate` |
| Break-glass admin checks (e.g. who is connected) | `careroute-db-bootstrap`, container `db-bootstrap` | `PYTHONUNBUFFERED=1 ADMIN_DATABASE_URL=secretref:database-url-admin` (read `ADMIN_DATABASE_URL` in the code) | server admin |

Use the least-privileged row that works.

Three rules, all learned by running it:
- An override replaces the whole container, so pass `--image` and the
  environment (`READ_ENV`/`MIGRATE_ENV`, from
  [Job environments](#job-environments)) every time. Without them it
  fails with `Image property` or `KeyError: 'DATABASE_URL'`.
- Attach Python's `-c` to the code, as in `"-cimport ..."`. A bare `-c` is
  parsed by `az` as its own flag and rejected. Keep the code on **one line**:
  a `\n` inside the quotes reaches Python literally and fails with a
  `SyntaxError`.
- Take the image from the job, so the query runs the deployed code:

```bash
IMG=$(az containerapp job show -g careroute-rg -n careroute-seed --query "properties.template.containers[0].image" -o tsv)
```

Example: look up one account (read-only):

```bash
az containerapp job start -g careroute-rg -n careroute-seed --container-name seed --image "$IMG" --env-vars "${READ_ENV[@]}" --command python --args "-cimport os, sqlalchemy as sa; e = sa.create_engine(os.environ['DATABASE_URL']); print(e.connect().execute(sa.text(\"select email, role, is_active from users where email = 'someone@example.com'\")).all())" --query name -o tsv
```

That prints the execution name. When
`az containerapp job execution show -g careroute-rg -n careroute-seed --job-execution-name <name> --query properties.status -o tsv`
says `Succeeded` (a few seconds of run time, plus a minute or two of
scheduling), read the output:

```bash
az containerapp job logs show -g careroute-rg -n careroute-seed --container seed --execution <name> --format text
```

The current schema revision, through the migrate job:

```bash
az containerapp job start -g careroute-rg -n careroute-migrate --container-name migrate --image "$IMG" --env-vars "${MIGRATE_ENV[@]}" --command alembic --args current --query name -o tsv
```

Status: **rehearsed** on 2026-09-25 (as admin, before the role split) and
2026-09-26 (as `careroute_app` through the seed job, reads succeeded and
`CREATE TABLE` was denied).

Know what you're doing when you use this:
- Through the seed job you are `careroute_app`: you can't damage the schema,
  but a typo in an `UPDATE`/`DELETE` still hits live data. Take a timestamp for
  point-in-time restore first.
- The command text is kept in the job's execution history and printed to the
  logs. **Never put a secret in it.** Never print `DATABASE_URL`.
- Anyone who can start a job can override its command and read the job's
  secrets. Treat "can start `careroute-db-bootstrap`" as admin on the database,
  and "can start `careroute-migrate`" as schema owner.
- Each execution bills a few seconds of consumption compute.

---

## Secrets and rotation

| Key Vault secret | Env var | Read by (identity) | Generated by |
|---|---|---|---|
| `database-url` | `DATABASE_URL` | API (`careroute-app-id`), seed (`careroute-seed-id`) | `random_password.pg_app`: role `careroute_app` |
| `database-url-migrate` | `DATABASE_URL` | migrate (`careroute-migrate-id`) | `random_password.pg_migrate`: role `careroute_migrate` |
| `database-url-admin` | `ADMIN_DATABASE_URL` | db-bootstrap (`careroute-dbbootstrap-id`) | `random_password.postgres_admin` |
| `db-app-password` / `db-migrate-password` | `APP_DB_PASSWORD` / `MIGRATE_DB_PASSWORD` | db-bootstrap | `random_password.pg_app` / `pg_migrate` |
| `jwt-secret` | `JWT_SECRET` | API, migrate, seed | `random_password.jwt_secret` |
| `demo-clinician-password` | `DEMO_CLINICIAN_PASSWORD` | seed | `random_password.demo_clinician` |
| `demo-coordinator-password` | `DEMO_COORDINATOR_PASSWORD` | seed | `random_password.demo_coordinator` |

Key Vault access is granted per secret, exactly as in this table, so the API's
identity can't read the migrate or admin credentials.

With `APP_ENV=production`, the API refuses to start if `JWT_SECRET` is still
the built-in development default. That makes a missing Key Vault reference
fail loudly instead of silently.

**To rotate a secret**, replace its generator. Terraform writes a new version
to Key Vault:

```bash
terraform apply "${TF_IMAGES[@]}" -replace=random_password.jwt_secret
```

(`TF_IMAGES`: see [Running Terraform by hand](#running-terraform-by-hand).)

The app references secrets **without a version**, so no other Terraform change
is needed. Per Microsoft's documentation, Container Apps retrieves the new
version **within 30 minutes** and restarts active revisions that use it. Don't
wait on that during an incident. Restart the running revision now:

```bash
az containerapp revision list -g careroute-rg -n careroute-api --query "[?properties.active].name" -o tsv
```

```bash
az containerapp revision restart -g careroute-rg -n careroute-api --revision <revision-name>
```

Jobs read secrets fresh on every execution, so they need nothing extra.

What each rotation does:

| Rotate | Resource | Effect |
|---|---|---|
| JWT signing key | `random_password.jwt_secret` | Every issued token fails at once. Everyone logs in again. This is the "log everyone out" lever |
| App role password | `random_password.pg_app` | The apply writes the new password to Key Vault, but the database still has the old one. **Immediately** run `careroute-db-bootstrap` (it sets the new password in Postgres), then restart the API. Between the apply and the bootstrap, any API restart, including Container Apps' own refresh within 30 minutes, picks up a password the database doesn't accept yet |
| Migrate role password | `random_password.pg_migrate` | Same: apply, then run `careroute-db-bootstrap`. Only the migrate job uses it, so there's no API impact |
| Server admin password | `random_password.postgres_admin` | One apply changes the admin password and `database-url-admin`. Only db-bootstrap uses it: no API impact |
| Demo passwords | `random_password.demo_clinician` / `demo_coordinator` | New values in Key Vault. Run `careroute-seed` again to apply them to the accounts |

If Terraform **state**, or a `*.tfplan` file, may have leaked, treat every
secret as exposed and rotate them all: `postgres_admin`, `pg_migrate`,
`pg_app`, `jwt_secret` and both demo passwords. Both contain every value. One
apply with a `-replace` for each, then db-bootstrap, then restart the API.
If the leak came through CI, cut CI off first (RUNBOOK → Who can read
production secrets).

Break-glass read of a secret (needs Key Vault Secrets Officer; prints the
value to your terminal, so be deliberate):

```bash
az keyvault secret show --vault-name $(terraform output -raw key_vault_name) --name jwt-secret --query value -o tsv
```

---

## Backups and restore

Azure backs up the server automatically, with point-in-time restore (PITR).
Retention is **7 days**, set by `backup_retention_days` in
`infra/database.tf`. Change it there, not with `az ... update`, or Terraform
will revert it on the next apply.

**Restore to a new server.** PITR always creates a **new** server and never
overwrites the live one. Put it on the same private network:

```bash
az postgres flexible-server restore -g careroute-rg --name careroute-pg-restore --source-server <postgres-server-name> --restore-time "2026-09-16T10:00:00Z" --subnet <snet-postgres-resource-id> --private-dns-zone <private-dns-zone-resource-id>
```

The server name is the first label of `terraform output -raw postgres_fqdn`.
Get the subnet and zone IDs with `az network vnet subnet show` and
`az network private-dns zone show`.

**Inspect it** with the in-VNet query above, pointed at the restored host:
build the URL inside the `python -c` from `DATABASE_URL`, swapping only the
hostname. The admin password is whatever the source server had at the
restore time.

**Known gaps** (open work, not yet solved):
- **Cutover isn't scripted.** The restored server isn't in Terraform state,
  and `database-url` is built from the Terraform-managed server. Promoting the
  restore means changing Terraform (import the new server, or re-point the
  secret), and that hasn't been designed or rehearsed. In practice, PITR here
  is for recovering and inspecting data, not for a full swap.
- **No logical dump/restore in Azure.** `scripts/backup.sh` and
  `scripts/restore.sh` target the local Compose stack
  ([BACKUP-RESTORE.md](BACKUP-RESTORE.md)). The hardened app image has no
  `pg_dump`/`pg_restore`, and no in-VNet job runs them, so there is no way to
  take a portable dump of the Azure database yet.
- **Delete restored servers when done.** Each one bills as a second B1ms.

---

## Cost

The target is under ~$20/month.

| What bills | Notes |
|---|---|
| Postgres B1ms + 32 GiB storage | Covered by Azure's free offer only for the first 12 months of a **new** subscription (750 hours/month = one server running continuously). Check the [current terms](https://azure.microsoft.com/pricing/details/postgresql/flexible-server/). Restored servers bill on top |
| Container Apps (consumption) | `min_replicas = 0`: scales to zero when idle, so the first request after a quiet period takes a few seconds. Job executions bill for their run time |
| Log Analytics | Hard cap of 0.5 GB/day |
| Key Vault | Per-operation, negligible at this volume |
| State storage | A few KB, pennies |

**No budget alert is provisioned.** Terraform doesn't create one. If you want
one, add it deliberately (manually, or as a Terraform resource). Don't assume
it exists.

Stopping Postgres saves compute but takes the API down: `/ready` returns 503
until it starts again, and Azure restarts a stopped server automatically after
7 days.

```bash
az postgres flexible-server stop -g careroute-rg -n <postgres-server-name>
```

---

## Teardown

Everything goes through Terraform:

```bash
cd infra && terraform destroy "${TF_IMAGES[@]}"
```

Then the CI identity, if you're removing everything:

```bash
cd infra/ci && terraform destroy
```

- The Key Vault is **soft-deleted** for 7 days, not purged
  (`purge_soft_delete_on_destroy = false`), so an accidental destroy is
  recoverable. Redeploying with the same vault name inside that window needs
  the vault purged or recovered first.
- The state backend (`careroute-tfstate-rg`) is untouched and carries a
  delete lock ([ADR-0006](adr/0006-terraform-state-backend.md)). Remove it only
  deliberately.

Don't `az group delete careroute-rg`. It deletes the resources behind
Terraform's back and leaves state describing things that no longer exist.
