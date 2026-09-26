output "api_url" {
  description = "Public URL of the API. Swagger UI is at /docs."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "resource_group" {
  value = azurerm_resource_group.app.name
}

output "key_vault_name" {
  description = "Holds database-url, jwt-secret and the private demo passwords."
  value       = azurerm_key_vault.main.name
}

output "postgres_fqdn" {
  description = "Private hostname; resolvable only inside the VNet."
  value       = azurerm_postgresql_flexible_server.main.fqdn
}

output "jobs" {
  description = "Manual-trigger jobs: az containerapp job start -g <resource_group> -n <name>"
  value = {
    migrate      = azurerm_container_app_job.migrate.name
    seed         = azurerm_container_app_job.seed.name
    db_bootstrap = azurerm_container_app_job.db_bootstrap.name
  }
}

output "app_image" {
  description = "Image the API, seed and db-bootstrap run. Pass back as -var app_image for infra-only applies."
  value       = var.app_image
}

output "migrate_image" {
  description = "Image the migrate job runs."
  value       = var.migrate_image
}
