---
phase: 01-ops-docs-match-deployment
status: passed
verified: 2026-09-25
---

# Phase 1 Verification: Ops Docs Match Deployment

Inline goal-backward check (the verifier agent was skipped at the user's request to keep cost down).

| # | Success criterion | Result | Evidence |
|---|---|---|---|
| 1 | AZURE.md: bootstrap → live via Terraform + Jobs; centralus, private PG, KV secrets; no firewall/hand-typed secrets | PASS | 01-01 grep checks; H2 structure; resource names match infra/*.tf |
| 2 | Every Azure RUNBOOK procedure **works against the live deployment** | PASS (approved scope) | The owner approved the rehearsal on 2026-09-25: logs, in-VNet query, `alembic current` all ran live and succeeded after doc fixes. Rotation, PITR and downgrade were deliberately not run on the live demo (owner-accepted), and the docs mark them unrehearsed |
| 3 | INCIDENT-RESPONSE rotation names random_password / Key Vault and the pick-up step | PASS | grep: `random_password.jwt_secret`, `random_password.postgres_admin`, `revision restart` |
| 4 | No instruction contradicts ADR-0006/0007/0008 | PASS | 01-02 cross-doc audit; every remaining hit is an allowed context |

User's extra checks: Container Apps not AKS (no AKS/K8s mentions anywhere); centralus stated, with the region-restriction reason; private Postgres with no public access; Key Vault-managed secrets; "Nothing here has been provisioned" replaced by "What's live" (the README's equivalent too).

## Human verification needed (criterion 2)
Low-cost rehearsal, only with owner approval (each job run bills seconds of compute):
1. `az containerapp logs show -g careroute-rg -n careroute-api --type console --tail 20` (free; confirms the log path)
2. One read-only in-VNet query via the migrate-job command override (AZURE.md example). Confirms the `--command/--args` override and the job logs path
3. `alembic current` via the same override
Not recommended on the live demo without a maintenance window: rotation, PITR restore, downgrade.

## Rehearsal results (2026-09-25, owner-approved)
| Step | Result |
|---|---|
| `az containerapp logs show ... --type console` | Works. **Finding:** it started a replica of the scaled-to-zero app to stream from. Documented |
| In-VNet query via migrate-job override | 1st try: `az` rejected a bare `-c`. 2nd: `ContainerAppImageRequired`. 3rd: `KeyError: 'DATABASE_URL'` (the override drops the env; safe failure, no DB access). With `--image`, `--env-vars` (secretref) and `"-cCODE"`, it returned `[('viewer@careroute.demo', 'viewer', True)]` |
| `alembic current` via override | `a6ca29d19c0c (head)` |

**Doc bug fixed as a result:** the "Deploying a new image" step 1 (`job start --image <new>` only) would have dropped the job's command and env. It would have started the API server in the job instead of migrating. It now passes `--env-vars "${JOB_ENV[@]}" --command alembic --args upgrade head`. The RUNBOOK downgrade command is fixed the same way. The corrected deploy-step form was **not** executed (it is a write path); its shape matches the rehearsed `alembic current` override.

Cost: 3 short job executions (2 succeeded, 1 failed fast) and one replica wake-up from `logs show`. Seconds of consumption compute.
