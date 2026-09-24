# Postgres 16 Flexible Server, private access only (VNet-injected; no public
# endpoint, so there is no firewall rule to get wrong). TLS is enforced by the
# server's default require_secure_transport=on; the app connects with
# sslmode=require.

resource "random_password" "postgres_admin" {
  length  = 32
  special = false # embedded in DATABASE_URL, so keep it URL-safe
}

resource "azurerm_postgresql_flexible_server" "main" {
  name                = "${local.name}-pg-${random_string.suffix.result}"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name

  version    = "16"
  sku_name   = var.postgres_sku
  storage_mb = 32768

  delegated_subnet_id           = azurerm_subnet.postgres.id
  private_dns_zone_id           = azurerm_private_dns_zone.postgres.id
  public_network_access_enabled = false

  administrator_login    = "careroute_admin"
  administrator_password = random_password.postgres_admin.result

  backup_retention_days        = 7
  geo_redundant_backup_enabled = false

  tags = local.tags

  depends_on = [azurerm_private_dns_zone_virtual_network_link.postgres]

  lifecycle {
    # Azure picks the availability zone; don't fight it on later plans.
    ignore_changes = [zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "careroute" {
  name      = "careroute"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}
