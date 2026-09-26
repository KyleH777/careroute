---
phase: 02-least-privilege-database-roles
plan: 03
status: complete
requirements: [DB-01]
completed: 2026-09-26
---

# 02-03 Summary: docs

- New ADR-0010 (roles, bootstrap, per-workload identities, per-secret Key Vault RBAC, staged rollout, consequences). The ADR index is updated; ADR-0007's "connects as the server admin" consequence is replaced; ADR-0008's status notes that its single identity is superseded.
- AZURE.md: architecture (identities, db-bootstrap job, a roles table: role → can → used by → secret → identity); first-time deployment runs db-bootstrap before migrate; `JOB_ENV` is split into `MIGRATE_ENV` / `READ_ENV`; a job table with the role per job; queries now go through the seed job as `careroute_app` (a role-per-purpose table; admin only via db-bootstrap, break-glass); the secrets table lists every secret with its reading identity; rotation covers pg_app/pg_migrate (apply → db-bootstrap immediately → restart) and postgres_admin (bootstrap only); state leak → rotate all.
- RUNBOOK.md: db-roles in first-five-minutes and "API won't start"; a new "Database roles" section (who uses what, plus a symptom table); lockout via the app role; the rollback downgrade uses MIGRATE_ENV.
- INCIDENT-RESPONSE.md: DB-credential containment per role; the state-leak bullet covers all random_passwords.
- BACKUP-RESTORE.md: run `db-roles` after a restore (verified in 02-01).
- README.md: startup ordering incl. db-roles and roles; `seed --reset` via migrate.

Checks: no stale strings; every documented secret exists in keyvault.tf; every job-override `--env-vars` set references only secrets defined on that job.
