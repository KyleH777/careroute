# One identity per workload, each allowed to read only the Key Vault secrets it
# needs (ADR-0010, amending ADR-0008's single shared identity). The API keeps
# careroute-app-id (keyvault.tf) so its identity isn't replaced.
#
# A compromised API can therefore read the app-role URL and the JWT key, but
# not the migrate or admin credentials.

resource "azurerm_user_assigned_identity" "workload" {
  for_each            = toset(["migrate", "seed", "dbbootstrap"])
  name                = "${local.name}-${each.key}-id"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  tags                = local.tags
}

locals {
  workload_identity = {
    api         = azurerm_user_assigned_identity.app
    migrate     = azurerm_user_assigned_identity.workload["migrate"]
    seed        = azurerm_user_assigned_identity.workload["seed"]
    dbbootstrap = azurerm_user_assigned_identity.workload["dbbootstrap"]
  }

  # migrations/env.py imports app.config, which requires JWT_SECRET in
  # production, so migrate needs jwt-secret too.
  workload_secrets = {
    api         = ["database-url", "jwt-secret"]
    migrate     = ["database-url-migrate", "jwt-secret"]
    seed        = ["database-url", "jwt-secret", "demo-clinician-password", "demo-coordinator-password"]
    dbbootstrap = ["database-url-admin", "db-migrate-password", "db-app-password"]
  }

  # Stage A grants only db-bootstrap; stage B grants everyone.
  secret_grants = {
    for pair in flatten([
      for workload, names in local.workload_secrets : [
        for name in names : { workload = workload, secret = name }
      ] if var.db_roles_enabled || workload == "dbbootstrap"
    ]) : "${pair.workload}/${pair.secret}" => pair
  }
}

resource "azurerm_role_assignment" "workload_secret" {
  for_each             = local.secret_grants
  scope                = azurerm_key_vault_secret.app[each.value.secret].resource_versionless_id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = local.workload_identity[each.value.workload].principal_id

  # Freshly created managed identities can take a while to replicate in
  # Entra ID; skip the lookup that would otherwise fail on first apply.
  skip_service_principal_aad_check = true
}

# Per-secret grants take a minute or two to take effect, like the vault-wide
# one (keyvault.tf). Re-sleeps whenever the set of grants changes.
resource "time_sleep" "workload_rbac_propagation" {
  create_duration = "90s"
  triggers = {
    grants = join(",", sort(keys(local.secret_grants)))
  }
  depends_on = [azurerm_role_assignment.workload_secret]
}
