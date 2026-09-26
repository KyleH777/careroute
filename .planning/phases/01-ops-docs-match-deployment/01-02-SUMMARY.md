---
phase: 01-ops-docs-match-deployment
plan: 02
status: complete
requirements: [DOCS-02, DOCS-03]
completed: 2026-09-25
---

# 01-02 Summary: RUNBOOK / INCIDENT-RESPONSE Azure paths

## What changed
- `docs/RUNBOOK.md`: Azure blocks for first five minutes (terraform output api_url, /health, /ready, console logs, migrate execution list), database unreachable (the firewall row is replaced by server state + VNet/private DNS), the JWT_SECRET start refusal (Key Vault ref + identity), one-user lookup/lockout (in-VNet job), token invalidation (`terraform apply -replace=random_password.jwt_secret` + `revision restart`), audit query, rollback 2a (variables.tf image + apply) and 2b (migrate job `--image <bad> --command alembic --args downgrade`), data loss (PITR). Fixed the `:latest` reasoning in "CI is red". Added Azure rows to the Reference table. The "verified" paragraph now says Azure steps are syntax-checked, not executed.
- `docs/INCIDENT-RESPONSE.md`: Azure forms in the Stabilize table; Azure evidence preservation (UTC timestamp for PITR + Log Analytics export); Contain rewritten for JWT and DB password via `random_password` + Key Vault + revision restart; new "state or tfplan exposed → rotate all four" bullet; rotation drill labelled dev stack, with an owner-approval note for Azure.
- `docs/BACKUP-RESTORE.md`: AZURE.md anchor link, plus a note that the scripts are Compose-only.

## Cross-doc audit (ROADMAP criterion 4)
Contradiction grep hits, all allowed:
- README.md:341 "not ... a hand-set app setting": states the opposite of the stale instruction.
- RUNBOOK.md:94, AZURE.md:52 "no firewall rules": affirms ADR-0007.
- `eastus` hits (AZURE.md:34, 59-60): state storage only, per ADR-0007.
- `token_urlsafe` (RUNBOOK.md:212, INCIDENT-RESPONSE.md:261): Compose/dev only.
- `:latest`: only as a published tag, never as an Azure deploy target.
AKS/Kubernetes/kubectl/helm: zero hits. All 5 AZURE.md anchors referenced from other docs exist.

## Deviations
None beyond carrying 01-01's variables.tf-not-`-var` deploy form into the rollback steps.

## Cost
No cost-incurring command run.
