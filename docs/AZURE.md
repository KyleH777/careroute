# Azure Database for PostgreSQL — Flexible Server

How to stand up the "prod" database and point CareRoute at it.

> **Nothing here has been provisioned.** These commands create billable cloud
> resources under your subscription, so running them is your call, not
> something done on your behalf. Everything below is written to be run as-is,
> but verify current free-tier terms before you start — Azure changes them, and
> the eligibility rules in particular are easy to trip over.

---

## Free tier, accurately

Azure's free offer for PostgreSQL Flexible Server covers, for the first 12
months of a **new** subscription:

- a **B1ms** burstable instance (1 vCore, 2 GiB RAM), up to 750 hours/month
- **32 GiB** of storage
- **32 GiB** of backup storage

Two things routinely surprise people:

1. **750 hours/month is one instance running continuously.** A second server,
   or a larger SKU, bills normally.
2. **The 12 months start with the subscription, not the server.** On an
   existing subscription older than a year, none of this is free.

Storage beyond 32 GiB, high availability, and read replicas are always billed.
Check the current terms before provisioning:
https://azure.microsoft.com/pricing/details/postgresql/flexible-server/

---

## Provisioning

Set your variables:

```bash
RG=careroute-rg; LOC=eastus; SERVER=careroute-pg-$RANDOM; ADMIN=carerouteadmin
```

The server name becomes a public DNS label, so it must be globally unique —
hence the `$RANDOM` suffix.

Log in and create the resource group:

```bash
az login
```

```bash
az group create --name $RG --location $LOC
```

Create the server on the free-tier-eligible SKU:

```bash
az postgres flexible-server create --resource-group $RG --name $SERVER --location $LOC --admin-user $ADMIN --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 --public-access None --yes
```

Notes on those flags:

- `--tier Burstable --sku-name Standard_B1ms --storage-size 32` is the
  combination the free offer covers. Anything larger bills.
- `--version 16` matches the `postgres:16-alpine` image used in dev. Keep dev
  and prod on the same major version — that is precisely where restore drills
  fail in real life.
- `--public-access None` starts with the firewall closed. You open it
  deliberately in the next step.
- Omitting `--admin-password` makes the CLI prompt for it, which keeps the
  password out of your shell history. Let it prompt.

Create the application database:

```bash
az postgres flexible-server db create --resource-group $RG --server-name $SERVER --database-name careroute
```

---

## Network access

For a quick connection from your current machine:

```bash
az postgres flexible-server firewall-rule create --resource-group $RG --name $SERVER --rule-name my-ip --start-ip-address $(curl -s ifconfig.me) --end-ip-address $(curl -s ifconfig.me)
```

For anything beyond a trial, prefer private access: put the server on a VNet
with a private endpoint and drop the public firewall rules entirely. A database
reachable from the public internet, protected only by a password, is the single
most common way these get compromised.

Never create the `0.0.0.0 – 255.255.255.255` rule, whatever a tutorial says.

---

## Connection string

Azure requires TLS. The psycopg driver takes `sslmode` straight from the URL:

```
postgresql+psycopg://carerouteadmin:<password>@<server>.postgres.database.azure.com:5432/careroute?sslmode=require
```

`app/config.py` reads this from `DATABASE_URL`, so no code changes are needed —
the same image runs against Compose in dev and Azure in prod.

**Do not put this in `docker-compose.yml` or any committed file.** Supply it as
a container App Setting, or better, store it in Key Vault and reference it.
`pool_pre_ping` is already enabled in `app/db.py`, which matters here: Azure
drops idle connections, and without pre-ping the first request after an idle
period fails on a stale connection.

### JWT signing secret

The API also needs `JWT_SECRET` and a non-dev `APP_ENV` (e.g. `production`).
With any `APP_ENV` other than `local`/`dev`/`test`, the app **refuses to start** if
`JWT_SECRET` is left at its built-in development default. Generate one and store
it in Key Vault alongside the connection string:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`scripts/seed.py` also refuses to run outside `local`/`dev`/`test`, because it creates
demo logins with a published password.

---

## Running migrations against Azure

The migrations ship inside the image, so run them with the same image you
deploy, pointing at the Azure URL:

```bash
docker run --rm -e DATABASE_URL="postgresql+psycopg://carerouteadmin:<password>@<server>.postgres.database.azure.com:5432/careroute?sslmode=require" careroute:local alembic upgrade head
```

Preview the SQL before it touches prod:

```bash
docker run --rm -e DATABASE_URL="postgresql+psycopg://user:pw@host:5432/careroute?sslmode=require" careroute:local alembic upgrade head --sql
```

`--sql` prints the statements instead of executing them, which is how you get a
reviewable change script for a production database.

Run migrations as a deliberate step in your deploy pipeline, not from the app's
startup path. On startup, multiple replicas race each other to migrate the same
schema.

---

## Backups on Azure

Azure takes automated backups with point-in-time restore. Default retention is
7 days; it is configurable up to 35.

```bash
az postgres flexible-server update --resource-group $RG --name $SERVER --backup-retention 14
```

Restore to a point in time — this creates a **new** server rather than
overwriting the existing one:

```bash
az postgres flexible-server restore --resource-group $RG --name $SERVER-restored --source-server $SERVER --restore-time "2026-09-16T10:00:00Z"
```

PITR and the `pg_dump` drill in [BACKUP-RESTORE.md](BACKUP-RESTORE.md) are
complements, not alternatives. PITR gives you fine-grained recovery but only
inside Azure and only within the retention window. The logical dumps are
portable, keepable indefinitely, and restorable to a laptop — which is what you
want for long-term archives, migrating providers, or a subscription-level
disaster.

Run the same drill against Azure at least once, so the procedure is proven
where it actually matters:

```bash
DB_SERVICE=db ./scripts/backup.sh pre-azure-cutover
```

---

## Cost control

Set a budget alert before you forget the server exists:

```bash
az consumption budget create --budget-name careroute-monthly --amount 10 --time-grain Monthly --category Cost --resource-group $RG
```

Burstable servers can be stopped when idle; they auto-start after 7 days.

```bash
az postgres flexible-server stop --resource-group $RG --name $SERVER
```

When the trial is over, delete everything in one move:

```bash
az group delete --name $RG --yes --no-wait
```
