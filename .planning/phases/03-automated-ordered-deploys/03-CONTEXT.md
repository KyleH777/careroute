# Phase 3: Automated Ordered Deploys - Context

**Gathered:** 2026-09-26
**Status:** Ready for planning

<domain>
Every push to `main` that passes CI deploys that commit's `sha-` image through Terraform, in ADR-0001 order, with OIDC-only Azure access. A failed migration stops the deploy with the old revision still serving.
</domain>

<decisions>
## Locked

### Deploy path (user choice 2026-09-26: "CI runs Terraform (as written)")
The recommended alternative (image-only deploys via a narrow role) was declined. CI runs `terraform apply` on the main config. Criterion 5's accepted risk applies: the CI identity can read every secret (state + Key Vault) and has owner-equivalent reach in `careroute-rg`. This is documented, and narrowed where possible (below).

### Ordering (closes the ADR-0001 hazard)
- Split `var.image` into `app_image` (API, seed, db-bootstrap) and `migrate_image` (migrate job). **No defaults.** Every apply must pass both, so a forgotten var errors instead of silently rolling back. Outputs `app_image`/`migrate_image` expose the live values.
- Deploy = stage 1 `apply -var migrate_image=NEW -var app_image=<current from output>` → start `careroute-migrate` (no override; its image is now NEW) → poll to Succeeded, else fail the run → stage 2 `apply -var migrate_image=NEW -var app_image=NEW` → smoke (`/ready` 200; active revision image == NEW; migrate job image == NEW).
- This supersedes Phase 1's "edit `image` in variables.tf" manual procedure.

### CI identity & blast-radius limits
- A user-assigned identity `careroute-ci-id` in a **separate RG `careroute-ci-rg`**, created by a separate human-applied Terraform root `infra/ci/` (own state key `careroute-ci.tfstate`). CI has no rights on careroute-ci-rg, so it can't edit its own federated credentials.
- Federated credential subject: `repo:KyleH777/careroute:environment:production`. The GitHub environment `production` allows only the `main` branch. PRs/forks can't mint a token.
- Role assignments (all created in `infra/ci/`):
  - Contributor on `careroute-rg`
  - Role Based Access Control Administrator on `careroute-rg`, **with an ABAC condition** limiting assignable roles to Key Vault Secrets User and Key Vault Secrets Officer (the only roles the main config assigns). This blocks self-escalation to Owner.
  - Storage Blob Data Contributor on the `tfstate` **container** only.
- Key Vault Secrets Officer: `deployer_secrets_officer` becomes `for_each` over {operator = var.operator_object_id, ci = CI principal via data source}, with a `moved` block keeping the existing human assignment. `var.operator_object_id` has no default (supplied via env `TF_VAR_operator_object_id` locally and as a GitHub environment variable), so no personal object ID is committed.

### Workflow safety
- Top-level CI concurrency: `cancel-in-progress` only for non-main refs. Deploy job concurrency group `deploy-production`, `cancel-in-progress: false`. Terraform's blob lease locks state too.
- `id-token: write` only on the deploy job. No `-out` plan files, no artifacts from infra/. Apply output is written to a runner-local file; only resource-action lines + the summary are printed. `TF_IN_AUTOMATION=1`.
- `workflow_dispatch` inputs: `simulate_migration_failure` (drill: the migrate step runs an override that exits 1) and `image_tag` (redeploy an existing tag = rollback when no schema change).

### Cost & outward actions
Checkpoints before: applying `infra/ci/` and the main-config refactor, creating the GitHub environment/variables, each push to main, the drill run. GitHub Actions is free (public repo); Azure cost per deploy is one job run + one revision.

## Claude's Discretion
Workflow step names; poll interval; exact smoke retries.
</decisions>

<canonical_refs>
- docs/adr/0001, 0006, 0008, 0010
- .planning/codebase INGEST-CONFLICTS.md (the ordering hazard): `.planning/INGEST-CONFLICTS.md`
- .github/workflows/ci.yml; infra/*.tf; docs/AZURE.md "Deploying a new image"; docs/RUNBOOK.md "Bad deploy / rollback"
</canonical_refs>

<deferred>
- The image-only deploy model (narrower CI role), declined for this phase; revisit if the accepted risk becomes unacceptable.
- Required reviewers on the `production` environment (would break "no human steps").
</deferred>
