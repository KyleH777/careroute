---
phase: 02-least-privilege-database-roles
plan: 02
status: complete
requirements: [DB-01]
completed: 2026-09-26
---

# 02-02 Summary: Azure rollout (stages A/B/C)

Every push, apply and job run was approved by the owner at a checkpoint. No plan file was written.

## Probe (Task 1)
`careroute` datdba = careroute_admin; the admin has CREATE on public; rolsuper = false; PG 16.15. Schema `public` is owned by `azure_pg_admin` (the admin inherits it), which differs from the local spike (pg_database_owner) and turned out fine.

## Push + CI
Pushed 11 commits (outgoing diff scanned first: no subscription ID, resource suffix or secrets). CI run 36213978101: lint, tests (incl. the role contract under the split) and publish all green. Image `sha-da96d74`; no migrations/app diff vs `sha-e15d28f`.

## Stage A (additive): 14 added, 3 changed (image), 0 destroyed
- Pre-existing drift found and handled: `snet-postgres` has a `Microsoft.Storage` service endpoint that Azure added and Terraform would have removed. It is now declared in network.tf rather than stripped from under the live server.
- `careroute-db-bootstrap`: created both roles; "10 object(s) changed owner" (the same count as the local upgrade rehearsal).
- Check (as admin): all public relations owned by careroute_migrate; neither role is super/createrole/createdb; 2 default ACLs; app can UPDATE referrals, cannot INSERT alembic_version, cannot CREATE in public. /ready 200.

## Stage B (switch): 9 added, 3 changed, 1 destroyed (time_sleep re-trigger)
- API revision restarted: /ready 200, authenticated worklist 200.
- `careroute-migrate` (migrate-id, careroute_migrate): Succeeded, alembic no-op. **Criterion 2.**
- `careroute-seed` (seed-id, careroute_app): Succeeded, "added 0 missing demo user(s)".
- pg_stat_activity: careroute_app ×1 (API pool), careroute_admin ×1 (the probe query itself). **Criterion 1.**
- App-role probe: `current_user` = careroute_app, reads OK (5 facilities), `CREATE TABLE` → `InsufficientPrivilege: permission denied for schema public`. **Criterion 1.**

## Stage C (tighten): 1 destroyed
- The first apply attempt failed at refresh with a transient `listing secrets for Job` error (nothing changed); an immediate re-plan was identical and the retry succeeded.
- After a 4-minute propagation wait: the API identity's assignments are exactly `secrets/database-url` and `secrets/jwt-secret`. The restarted API: /ready 200, worklist 200, no Key Vault errors in system logs. **Criterion 3.**

## Deviations
- The DDL probe first failed on shell quoting (`\n` passed literally to python -c); it was re-run as a single line that lets the error surface. Rule for the docs: keep `-c` code on one line.
- network.tf service endpoint (above), outside the planned file list.
