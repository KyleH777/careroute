# Identifiers, not secrets: set as variables on the GitHub `production`
# environment (AZURE_CLIENT_ID, AZURE_TENANT_ID).
output "client_id" {
  value = azurerm_user_assigned_identity.ci.client_id
}

output "tenant_id" {
  value = azurerm_user_assigned_identity.ci.tenant_id
}

output "principal_id" {
  value = azurerm_user_assigned_identity.ci.principal_id
}
