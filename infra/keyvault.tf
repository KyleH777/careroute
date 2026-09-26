# Every secret the app needs, generated here and stored in Key Vault. The
# containers read them through a user-assigned managed identity, so no secret
# appears in the Container App configuration, and none is typed by a human.
#
# Note: these values are also in Terraform state. That state lives in the
# locked-down storage account (Entra-only access, versioned), which is why
# the backend is set up the way it is.

resource "azurerm_key_vault" "main" {
  name                = "kv-${local.name}-${random_string.suffix.result}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  tenant_id           = data.azurerm_client_config.current.tenant_id
  sku_name            = "standard"

  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false # allows a clean destroy/recreate of this demo

  tags = local.tags
}

resource "azurerm_user_assigned_identity" "app" {
  name                = "${local.name}-app-id"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  tags                = local.tags
}

# You (whoever runs terraform) write the secrets...
resource "azurerm_role_assignment" "deployer_secrets_officer" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# ...and the app's identity may only read them. Pre-ADR-0010 this was
# vault-wide; per-secret grants now live in identities.tf, and stage C drops
# this one (var.legacy_vault_wide_app_access = false).
moved {
  from = azurerm_role_assignment.app_secrets_user
  to   = azurerm_role_assignment.app_secrets_user[0]
}

resource "azurerm_role_assignment" "app_secrets_user" {
  count                = var.legacy_vault_wide_app_access ? 1 : 0
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Role assignments take a minute or two to take effect; writing secrets (or
# creating apps that read them) immediately afterwards fails with 403.
resource "time_sleep" "rbac_propagation" {
  create_duration = "90s"
  depends_on = [
    azurerm_role_assignment.deployer_secrets_officer,
    azurerm_role_assignment.app_secrets_user,
  ]
}

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "random_password" "demo_clinician" {
  length = 24
}

resource "random_password" "demo_coordinator" {
  length = 24
}

locals {
  db_url = {
    for role, pw in {
      (azurerm_postgresql_flexible_server.main.administrator_login) = random_password.postgres_admin.result
      (local.db_role_migrate)                                       = random_password.pg_migrate.result
      (local.db_role_app)                                           = random_password.pg_app.result
      } : role => format(
      "postgresql+psycopg://%s:%s@%s:5432/%s?sslmode=require",
      role,
      pw,
      azurerm_postgresql_flexible_server.main.fqdn,
      azurerm_postgresql_flexible_server_database.careroute.name,
    )
  }
  admin_db_url = local.db_url[azurerm_postgresql_flexible_server.main.administrator_login]

  secrets = {
    # What the API (and seed) connect with: the DML-only role once stage B is
    # on, the server admin before that.
    "database-url"         = var.db_roles_enabled ? local.db_url[local.db_role_app] : local.admin_db_url
    "database-url-migrate" = local.db_url[local.db_role_migrate]
    "database-url-admin"   = local.admin_db_url # db-bootstrap only
    "db-migrate-password"  = random_password.pg_migrate.result
    "db-app-password"      = random_password.pg_app.result

    "jwt-secret"                = random_password.jwt_secret.result
    "demo-clinician-password"   = random_password.demo_clinician.result
    "demo-coordinator-password" = random_password.demo_coordinator.result
  }
}

resource "azurerm_key_vault_secret" "app" {
  for_each     = local.secrets
  name         = each.key
  value        = each.value
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [time_sleep.rbac_propagation]
}
