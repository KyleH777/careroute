---
phase: 01-ops-docs-match-deployment
status: human_needed
verified: 2026-09-25
---

# Phase 1 Verification: Ops Docs Match Deployment

Inline goal-backward check (the verifier agent was skipped at the user's request to keep cost down).

| # | Success criterion | Result | Evidence |
|---|---|---|---|
| 1 | AZURE.md: bootstrap → live via Terraform + Jobs; centralus, private PG, KV secrets; no firewall/hand-typed secrets | PASS | 01-01 grep checks; H2 structure; resource names match infra/*.tf |
| 2 | Every Azure RUNBOOK procedure **works against the live deployment** | PARTIAL: human_needed | Procedures exist and are syntax-checked against `az --help` and infra/*.tf. None were executed live, per the user's cost instruction |
| 3 | INCIDENT-RESPONSE rotation names random_password / Key Vault and the pick-up step | PASS | grep: `random_password.jwt_secret`, `random_password.postgres_admin`, `revision restart` |
| 4 | No instruction contradicts ADR-0006/0007/0008 | PASS | 01-02 cross-doc audit; every remaining hit is an allowed context |

User's extra checks: Container Apps not AKS (no AKS/K8s mentions anywhere); centralus stated, with the region-restriction reason; private Postgres with no public access; Key Vault-managed secrets; "Nothing here has been provisioned" replaced by "What's live" (the README's equivalent too).

## Human verification needed (criterion 2)
Low-cost rehearsal, only with owner approval (each job run bills seconds of compute):
1. `az containerapp logs show -g careroute-rg -n careroute-api --type console --tail 20` (free; confirms the log path)
2. One read-only in-VNet query via the migrate-job command override (AZURE.md example). Confirms the `--command/--args` override and the job logs path
3. `alembic current` via the same override
Not recommended on the live demo without a maintenance window: rotation, PITR restore, downgrade.
