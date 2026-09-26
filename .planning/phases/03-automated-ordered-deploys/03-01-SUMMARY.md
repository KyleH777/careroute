---
phase: 03-automated-ordered-deploys
plan: 01
status: complete
requirements: [DEPLOY-01, DEPLOY-02]
completed: 2026-09-26
---

# 03-01 Summary

- Main config: `app_image` (API, seed, db-bootstrap) and `migrate_image` (migrate), both required with no default; `operator_object_id` (no default, via TF_VAR); Secrets Officer is `for_each` {operator, ci} with a `moved` for the existing assignment; outputs `app_image`/`migrate_image`.
- `infra/ci/` (own state key `careroute-ci.tfstate`): careroute-ci-rg, careroute-ci-id, federated credential `repo:KyleH777/careroute:environment:production`, Contributor + conditioned RBAC Admin (assign/remove only KV Secrets User/Officer) on careroute-rg, Storage Blob Data Contributor on the tfstate container.
- Applied: infra/ci +6; main +1 (CI Secrets Officer) with the operator assignment moved; images unchanged (sha-da96d74).
- Verified: CI principal has exactly 4 assignments (RBAC Admin conditioned); 1 federated credential (production subject).

## Deviations
- The `azurerm_storage_account` data source fails on the state account (it lists keys; keys are disabled per ADR-0006). The container scope is built from the subscription ID + account name instead.
- The `retrieving/listing secrets for Container App/Job` refresh error recurred intermittently (2nd occurrence; immediate re-runs are clean). 03-02's deploy job must retry an apply once on exactly this error.
