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
| Managed identity | `careroute-app-id` | The only identity the app and jobs use to read secrets |
| Role assignments | Key Vault Secrets Officer (whoever runs Terraform), Key Vault Secrets User (`careroute-app-id`) | Write vs. read access to secrets |
| Log Analytics workspace | `careroute-logs` | Container logs, 30-day retention, 0.5 GB/day ingestion cap |
| Container Apps environment | `careroute-env` | Consumption workload profile, VNet-integrated |
| Container App | `careroute-api` | The API. External ingress on port 8000, 0-2 replicas, liveness `/health`, readiness `/ready` |
| Container Apps Job | `careroute-migrate` | `alembic upgrade head`, manual trigger |
| Container Apps Job | `careroute-seed` | `python scripts/seed.py --demo-deployment`, manual trigger |

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
to Key Vault. The Container App and both jobs read secrets through
`careroute-app-id`, using versionless Key Vault references. No human types,
sees or pastes a production secret. Why:
[ADR-0008](adr/0008-secrets-generated-into-key-vault.md). The same values are
also in Terraform state, which is why the state backend is locked down
([ADR-0006](adr/0006-terraform-state-backend.md)).

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

**2. Initialise Terraform:**

```bash
cd infra
```

```bash
export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
```

```bash
terraform init -backend-config=backend.hcl
```

**3. Plan, review, apply:**

```bash
terraform plan -out=careroute.tfplan
```

```bash
terraform apply careroute.tfplan
```

**4. Delete the plan file.** Plan files embed every secret. `*.tfplan` is
git-ignored, but that only keeps it out of git, not off your disk.

```bash
rm careroute.tfplan
```

**5. Migrate, then seed.** Terraform never runs the jobs itself. On a fresh
database the API is up before any tables exist. `/ready` still returns 200
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

Until CI automates this (roadmap Phase 3), deploys are manual, and **the order
matters**: migrate with the new image first, then roll the app
([ADR-0001](adr/0001-one-shot-migration-before-api.md)).

**1. Run the new image's migrations**, overriding the job's image for this one
execution. An override **replaces the job's whole container definition**, so
the command and environment must be passed again. Without them the job starts
the image's default command, which is the API server, with no database URL.
Set the environment once per shell:

```bash
JOB_ENV=(APP_ENV=production PYTHONUNBUFFERED=1 DATABASE_URL=secretref:database-url JWT_SECRET=secretref:jwt-secret)
```

```bash
az containerapp job start -g careroute-rg -n careroute-migrate --container-name migrate --image ghcr.io/kyleh777/careroute:sha-<new> --env-vars "${JOB_ENV[@]}" --command alembic --args upgrade head
```

```bash
az containerapp job execution list -g careroute-rg -n careroute-migrate -o table
```

Stop here if the execution didn't succeed. The API is still on the old image,
and the migration rolled back (Postgres DDL is transactional). Read the job
logs ([Logs](#logs)).

**2. Roll the app** to the same tag. Set `default` for `image` in
`infra/variables.tf` to `ghcr.io/kyleh777/careroute:sha-<new>`, then:

```bash
terraform apply
```

Commit the `variables.tf` change. Don't use `-var image=...`: the next apply
without that flag (a secret rotation, say) would silently roll the app back to
whatever `variables.tf` says.

> ⚠️ Don't skip step 1. A plain `terraform apply` with a new image updates the
> migrate job **and** the API in one go, so the API can serve the new code
> against the old schema before anyone runs the migration.

Always deploy an immutable `sha-` tag. `variables.tf` rejects `:latest`, so
rollback is the same edit-and-apply with the previous tag (RUNBOOK → Bad deploy).

---

## Migrations and seeding

Both jobs run the deployed image with the same environment and secrets as the
API.

| | `careroute-migrate` | `careroute-seed` |
|---|---|---|
| Command | `alembic upgrade head` | `python scripts/seed.py --demo-deployment` |
| Trigger | Manual | Manual |
| Timeout | 600 s | 600 s |
| Retries | **0**: a failed migration needs a human, not a retry | 0 |
| Secrets | `database-url`, `jwt-secret` | Those plus both private demo passwords |

To review a migration's SQL before it runs in production, render it against
the **local** stack. The SQL is the same, and no production credentials are
involved:

```bash
docker compose run --rm migrate alembic upgrade head --sql
```

---

## Logs

API console output, most recent first:

```bash
az containerapp logs show -g careroute-rg -n careroute-api --type console --tail 100
```

Add `--follow` to stream. Use `--type system` for platform events such as
image pulls, probe failures, Key Vault reference errors and restarts.

`logs show` streams from a **running replica**. If the API has scaled to zero,
it starts one (seen 2026-09-25), which costs a few seconds of compute and shows
only that fresh replica's output. For anything that happened before, use Log
Analytics, below.

A job's output (defaults to its latest execution):

```bash
az containerapp job logs show -g careroute-rg -n careroute-migrate --container migrate
```

Anything older, or anything you need to filter, is in the Log Analytics
workspace `careroute-logs`, table `ContainerAppConsoleLogs_CL`:

```kusto
ContainerAppConsoleLogs_CL
| where ContainerAppName_s == "careroute-api"
| where TimeGenerated > ago(1h)
| project TimeGenerated, RevisionName_s, Log_s
| order by TimeGenerated desc
```

Two limits to know during an incident:
- Retention is **30 days**. Export anything you need as evidence before it
  ages out.
- Ingestion is capped at **0.5 GB/day** as a cost guard. Past the cap, logs
  **stop being collected** until the next day. A noisy failure can therefore
  hide the logs that come after it.

---

## Querying the database from inside the VNet

A laptop can't reach the database: it has no public endpoint, by design. To
run a one-off query, start the migrate job with a **command override**. It
runs inside the VNet. The image has Python, SQLAlchemy and psycopg, but no
shell and no `psql`.

Three rules, all learned by running it:
- An override replaces the whole container, so pass `--image` and the
  environment (`JOB_ENV`, from [Deploying a new image](#deploying-a-new-image))
  every time. Without them it fails with `Image property` or
  `KeyError: 'DATABASE_URL'`.
- Attach Python's `-c` to the code, as in `"-cimport ..."`. A bare `-c` is
  parsed by `az` as its own flag and rejected.
- Take the image from the job, so the query runs the deployed code:

```bash
IMG=$(az containerapp job show -g careroute-rg -n careroute-migrate --query "properties.template.containers[0].image" -o tsv)
```

Example: look up one account (read-only):

```bash
az containerapp job start -g careroute-rg -n careroute-migrate --container-name migrate --image "$IMG" --env-vars "${JOB_ENV[@]}" --command python --args "-cimport os, sqlalchemy as sa; e = sa.create_engine(os.environ['DATABASE_URL']); print(e.connect().execute(sa.text(\"select email, role, is_active from users where email = 'someone@example.com'\")).all())" --query name -o tsv
```

That prints the execution name. When
`az containerapp job execution show -g careroute-rg -n careroute-migrate --job-execution-name <name> --query properties.status -o tsv`
says `Succeeded` (a few seconds of run time, plus a minute or two of
scheduling), read the output:

```bash
az containerapp job logs show -g careroute-rg -n careroute-migrate --container migrate --execution <name> --format text
```

The current schema revision, the same way:

```bash
az containerapp job start -g careroute-rg -n careroute-migrate --container-name migrate --image "$IMG" --env-vars "${JOB_ENV[@]}" --command alembic --args current --query name -o tsv
```

Status: **rehearsed on 2026-09-25**. The account lookup returned the demo
viewer row, and `alembic current` returned `a6ca29d19c0c (head)`.

Know what you're doing when you use this:
- It connects as the **server admin** (the app has no least-privilege role
  yet; roadmap Phase 2). A typo in a write statement hits live data. Take a
  timestamp for point-in-time restore first.
- The command text is kept in the job's execution history and printed to the
  logs. **Never put a secret in it.** Never print `DATABASE_URL`.
- Anyone who can start a job can override its command and read the job's
  secrets. Treat "can start `careroute-migrate`" as "can read the database
  password".
- Each execution bills a few seconds of consumption compute.

---

## Secrets and rotation

| Key Vault secret | Env var | Read by | Generated by |
|---|---|---|---|
| `database-url` | `DATABASE_URL` | API, migrate, seed | `random_password.postgres_admin` + server FQDN |
| `jwt-secret` | `JWT_SECRET` | API, migrate, seed | `random_password.jwt_secret` |
| `demo-clinician-password` | `DEMO_CLINICIAN_PASSWORD` | seed | `random_password.demo_clinician` |
| `demo-coordinator-password` | `DEMO_COORDINATOR_PASSWORD` | seed | `random_password.demo_coordinator` |

With `APP_ENV=production`, the API refuses to start if `JWT_SECRET` is still
the built-in development default. That makes a missing Key Vault reference
fail loudly instead of silently.

**To rotate a secret**, replace its generator. Terraform writes a new version
to Key Vault:

```bash
terraform apply -replace=random_password.jwt_secret
```

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
| Database password | `random_password.postgres_admin` | One apply changes the server's admin password **and** the `database-url` secret. Until the API restarts, it holds the old password: `/ready` returns 503 and requests fail. Restart straight away, off-hours if you can |
| Demo passwords | `random_password.demo_clinician` / `demo_coordinator` | New values in Key Vault. Run `careroute-seed` again to apply them to the accounts |

If Terraform **state**, or a `*.tfplan` file, may have leaked, treat all four
secrets as exposed and rotate them all. Both contain every value.

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
cd infra && terraform destroy
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
