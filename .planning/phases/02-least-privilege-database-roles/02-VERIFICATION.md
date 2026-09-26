---
phase: 02-least-privilege-database-roles
status: passed
verified: 2026-09-26
---

# Phase 2 Verification: Least-Privilege Database Roles

Inline goal-backward check (verifier agent skipped to limit cost).

| # | Success criterion | Result | Evidence |
|---|---|---|---|
| 1 | Live API sessions as a dedicated app role; DML ok; DDL denied | PASS | pg_stat_activity: careroute_app (API pool); app-role probe reads OK, `CREATE TABLE` → `permission denied for schema public` (02-02) |
| 2 | Migrate runs as a separate owner role; future tables usable without GRANT; neither role is admin | PASS | careroute-migrate Succeeded as careroute_migrate; 2 default ACLs live; the local round-trip + contract tests prove new tables are app-writable (02-01) |
| 3 | Role passwords are Terraform random_password in Key Vault via managed identity; created in-VNet | PASS | random_password.pg_app/pg_migrate → KV; db-bootstrap job (in-VNet) created the roles; API identity limited to database-url + jwt-secret (stage C) |
| 4 | Compose + CI use the same split; a missing grant fails CI | PASS | db-roles in both compose files; tests/test_db_roles.py; CI run 36213978101 green |
| 5 | Docs describe roles, who uses which, and how to rotate each | PASS | ADR-0010, AZURE.md roles/secrets/rotation tables, RUNBOOK "Database roles" (02-03) |

Extra hardening beyond the criteria: per-workload identities with per-secret Key Vault access (user decision).
