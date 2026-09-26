# Phase 3 Research: Automated Ordered Deploys

**Date:** 2026-09-26 · free sources only (provider schema, Microsoft Learn, repo inspection)

## Verified
| Topic | Finding | Source |
|---|---|---|
| Federated credential | `azurerm_federated_identity_credential` needs `name, audience, issuer, subject`, plus `user_assigned_identity_id`. `parent_id` / `resource_group_name` are **deprecated** in azurerm 4.81 | `terraform providers schema` |
| Job data source | No `azurerm_container_app_job` data source exists, so "keep the live image when unset" can't be done in HCL. Decision: required image variables with no default, plus outputs | same |
| Role assignment conditions | `azurerm_role_assignment` supports `condition` + `condition_version = "2.0"` | same |
| Constrained delegation | Condition template "Constrain roles": `((!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {<ids>})) AND ((!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {<ids>}))` on a **Role Based Access Control Administrator** assignment | learn.microsoft.com/azure/role-based-access-control/delegate-role-assignments-examples |
| Failed revision | Single revision mode: "If an update fails, traffic remains pointed to the old revision." The old revision isn't deactivated until the new one passes readiness | learn.microsoft.com/azure/container-apps/revisions |

## Hazards found in the current repo (must fix)
1. `azurerm_role_assignment.deployer_secrets_officer` uses `data.azurerm_client_config.current.object_id`. When CI applies, that's the CI identity, so the human's Secrets Officer would be **replaced** by CI's.
2. `.github/workflows/ci.yml` top-level `concurrency: cancel-in-progress: true` applies to `main`, so a second push would cancel a deploy mid-apply.
3. The single `var.image` feeds both the app and the migrate job (the ADR-0001 hazard).
4. If the CI identity lived in `careroute-rg`, Contributor there could add federated credentials to it (a persistent backdoor). It goes in `careroute-ci-rg`, where CI has no role.

## To confirm at execution (free)
- Role definition GUIDs for Key Vault Secrets User / Officer: `az role definition list --name "Key Vault Secrets User" --query [].name -o tsv`.
- azurerm backend + provider OIDC env: `ARM_USE_OIDC=true`, `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID` (backend keeps `use_azuread_auth = true`).
