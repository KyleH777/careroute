---
phase: 05-login-hardening
plan: 03
status: complete
requirements: [LOGIN-01, LOGIN-02]
completed: 2026-09-29
---
# 05-03 Summary
ADR-0013 (+ index); RUNBOOK "Login attempts" with a `sql()` helper (seed-job override, app role) and 5 SQL queries + 1 KQL: all run live (account: 8 rows; IP: 2 groups; top IPs: 1; unlock: 5 rows deleted, which also cleared the drill lock; prune: 0); INCIDENT-RESPONSE gap removed and login evidence added to scoping; AZURE.md "Client IPs behind ingress"; README bullet.
