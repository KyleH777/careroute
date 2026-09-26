---
phase: 01-ops-docs-match-deployment
plan: 01
status: complete
requirements: [DOCS-01]
completed: 2026-09-25
---

# 01-01 Summary: AZURE.md as built + README corrections

## Decision (checkpoint)
Restore path: **PITR + name the gap** (user choice). No infra added.

## What changed
- `docs/AZURE.md` rewritten. The false "Nothing here has been provisioned" is replaced by a "What's live" callout. H2s, in order: Architecture, First-time deployment, Deploying a new image, Migrations and seeding, Logs, Querying the database from inside the VNet, Secrets and rotation, Backups and restore, Cost, Teardown.
- Removed: the eastus `az ... create` provisioning, the firewall-rule section, the hand-built connection string, the hand-generated JWT secret, laptop `docker run` migrations against Azure, `az ... update --backup-retention`, the implied budget alert, and `az group delete` cleanup.
- `README.md`: IaC section now describes what infra/ declares; the Deploying section no longer says "Nothing there has been provisioned"; the Operations bullet says Azure procedures are syntax-checked, not rehearsed.

## Deviations
- **Deploy/rollback uses editing `image` in variables.tf + `terraform apply`, not `-var image=`** (plan said `-var`). Reason: a later plain apply (for example a secret rotation) would silently roll the app back to the variables.tf default. Plan 01-02 must use the same form.
- **Rotation wording:** Microsoft Learn (manage-secrets, updated 2026-09-11) says versionless KV refs are picked up within 30 minutes and active revisions restart automatically. The docs say this and still tell operators to `revision restart` straight away during an incident.
- Added a security note from the same page: start-job permission effectively grants the job's secrets (command override).
- Fixed a claim of my own: `/ready` only does `SELECT 1`, so it passes on an unmigrated DB. The doc says data requests fail until migrate runs.

## Verification (all free)
- Plan grep for stale strings: one allowed hit, the "Don't `az group delete careroute-rg`" warning.
- All `az` subcommands used exist per `--help`: job start/execution list/logs show, revision list/restart, logs show, postgres flexible-server restore/stop/show, keyvault secret show.
- `terraform fmt -check` and `terraform validate`: pass. No .tf touched.
- No cost-incurring command run. Nothing was executed against live Azure during execution.

## Known gaps recorded in AZURE.md
PITR cutover isn't scripted (the restored server is outside Terraform state); there is no in-VNet logical dump/restore; no budget alert is provisioned.
