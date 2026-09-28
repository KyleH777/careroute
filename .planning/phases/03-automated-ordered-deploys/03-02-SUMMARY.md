---
phase: 03-automated-ordered-deploys
plan: 02
status: complete
requirements: [DEPLOY-01, DEPLOY-02, DEPLOY-03]
completed: 2026-09-28
---

# 03-02 Summary: ordered OIDC deploy

## Built
- GitHub environment `production` (deployment branches: `main` only), with environment **secrets** AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_SUBSCRIPTION_ID / TF_VAR_OPERATOR_OBJECT_ID (identifiers, masked in public logs; the user left the choice to Claude). No Azure credential is stored.
- `.github/workflows/ci.yml`: main runs are never cancelled; `workflow_dispatch` (`image_tag`, `simulate_migration_failure`); the `image` job outputs `tag`; the `deploy` job (environment production, `id-token: write` only here, concurrency `deploy-production` with no cancel).
- `.github/scripts/deploy.sh`: `apply` (output kept on the runner; prints only resource actions/errors; retries once on the known transient secrets-read error), `migrate` (plain run or drill override; polls; any non-Succeeded fails), `smoke` (/ready 200, both images == new, waits for the active revision to run the new image).

## Fixes found by running it (deviations)
1. **OIDC subject format**: GitHub presents `repo:KyleH777@88053223/careroute@1383757448:environment:production` (immutable IDs), so the name-only subject failed with AADSTS700213. infra/ci now uses the ID form (also rename-safe).
2. **CI couldn't read its own identity** (403 on `data.azurerm_user_assigned_identity.ci`): added Reader on careroute-ci-id only (it can't write federated credentials).
3. The smoke check read the active revision mid-switch; it now waits for the active revision to carry the new image.

## Evidence
- **Criterion 1/2**: run 36261898752 (rerun, sha-c3bb05b): stage 1 "1 changed" (migrate job only) → `careroute-migrate-554qohl` Succeeded 01:44:47 → stage 2 "3 changed" (api, seed, db-bootstrap) → new revision `careroute-api--0000002` created 01:45:56 (after the migration) → smoke /ready 200, both images sha-c3bb05b. Run 36373063429 (push of 6069293, no human step): the same sequence, `careroute-migrate-dasthsa` Succeeded → `careroute-api--0000003` active on sha-6069293.
- **Criterion 3 (drill)**: run 36374139943 (`simulate_migration_failure=true`): `careroute-migrate-2tei68o` Failed ("drill: simulated migration failure"), the Migrate step failed, stage 2 + smoke skipped, no new revision (`--0000003` still active, sha-6069293), /ready 200.
- **Criterion 4**: the single federated credential is `...:environment:production`; the environment only allows `main`; GitHub holds IDs only. CI grants: Contributor + conditioned RBAC Admin on careroute-rg, Blob Data Contributor on the tfstate container, KV Secrets Officer, Reader on its own identity.
