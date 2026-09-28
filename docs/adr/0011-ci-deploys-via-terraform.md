# ADR-0011: CI deploys by running Terraform, in two stages

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

Deploys were manual: migrate with the new image, then apply Terraform for the app. Forgetting the first step, or a single `terraform apply` that moved both images at once, would serve new code against the old schema (ADR-0001). The requirement (DEPLOY-01) was that every `main` push deploys itself, in order, with no stored Azure credential.

A narrower model was considered: CI only sets images through a custom role on the app and migrate job, with Terraform ignoring image changes. It was declined (2026-09-26) in favour of CI applying the real Terraform config, so the deployed infrastructure never drifts from `main`.

## Decision

- **Two-stage apply.** `migrate_image` and `app_image` are separate, required variables. The `deploy` job applies the new migrate image only, runs `careroute-migrate` and requires `Succeeded`, then applies the new app image and smoke-checks (`.github/scripts/deploy.sh`). A failed migration stops the run before the app changes.
- **OIDC only.** GitHub Actions signs in as `careroute-ci-id` via a federated credential whose subject is the `production` environment, in GitHub's immutable-ID form (`repo:KyleH777@88053223/careroute@1383757448:environment:production`). The environment only accepts `main`, so PR and fork runs can't get a token. GitHub stores identifiers, no secret.
- **Bounded, not minimal.** `careroute-ci-id` lives in `careroute-ci-rg`, created by the human-applied `infra/ci` root, so CI can't edit its own credentials. It holds: Contributor on `careroute-rg`; Role Based Access Control Administrator there, conditioned to assign/remove only Key Vault Secrets User/Officer; Storage Blob Data Contributor on the `tfstate` container; Key Vault Secrets Officer; Reader on its own identity.
- **Serialized.** One deploy at a time (`deploy-production` concurrency, never cancelled), plus the state blob lease. Pushes to `main` never cancel a running workflow.
- **No secret output.** No plan files, no artifacts; apply output stays on the runner and only resource actions and errors are printed.

## Consequences

- **Accepted risk:** CI can read every production secret (state and Key Vault), and anything that can run code in the `deploy` job, i.e. anyone who can push to `main` or change its workflows, can too. Within `careroute-rg` it can do anything except grant roles other than the two Key Vault roles. The mitigation is branch protection on `main`, the "Who can read production secrets" list in the runbook, and a one-command cut-off (delete the federated credential).
- Humans applying Terraform must pass the live images (`TF_IMAGES`, AZURE.md) and `TF_VAR_operator_object_id`; forgetting either fails instead of rolling something back.
- Infra changes should go through `main`: a manual apply that isn't committed is reverted by the next deploy.
- Rollback without a schema change is a `workflow_dispatch` with `image_tag`. With a schema change, the downgrade stays a manual, deliberate step (a deploy of an older image whose schema is behind fails safely at migrate).
- The failing-migration drill (`simulate_migration_failure`) proves DEPLOY-03 on demand.
