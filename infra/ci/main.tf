# The identity GitHub Actions uses to deploy CareRoute (ADR-0011).
#
# Applied by a human only, never by CI, and kept in its own resource group
# where CI holds no role. If the identity lived in careroute-rg, CI's
# Contributor there could add a federated credential trusting any repo to
# its own identity: a permanent backdoor.
#
#   cd infra/ci
#   terraform init -backend-config=../backend.hcl
#   terraform apply
#
# What the identity can do, and nothing more:
#   - sign in only from this repo's `production` GitHub environment (main only)
#   - Contributor on careroute-rg
#   - Role Based Access Control Administrator on careroute-rg, conditioned to
#     assign/remove only Key Vault Secrets User/Officer (all the main config
#     assigns), so it can't grant itself Owner
#   - Storage Blob Data Contributor on the tfstate container only
# Accepted in ADR-0011: this means CI can read every secret.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  backend "azurerm" {
    resource_group_name = "careroute-tfstate-rg"
    container_name      = "tfstate"
    key                 = "careroute-ci.tfstate"
    use_azuread_auth    = true
  }
}

provider "azurerm" {
  features {}
}

locals {
  tags = {
    project    = "careroute"
    managed-by = "terraform"
    purpose    = "ci-identity"
  }

  # Built-in role definition IDs (az role definition list --name ...).
  kv_secrets_user_role    = "4633458b-17de-408a-b874-0445c86b69e6"
  kv_secrets_officer_role = "b86a8fe4-44ce-4948-aee5-eccb2c155cd7"
  assignable_roles        = "${local.kv_secrets_user_role}, ${local.kv_secrets_officer_role}"
}

data "azurerm_resource_group" "app" {
  name = var.app_resource_group
}

data "azurerm_subscription" "current" {}

# Built from its ID rather than via the azurerm_storage_account data source,
# which lists account keys, and keys are disabled on this account (ADR-0006).
locals {
  tfstate_container_id = "${data.azurerm_subscription.current.id}/resourceGroups/careroute-tfstate-rg/providers/Microsoft.Storage/storageAccounts/${var.state_storage_account}/blobServices/default/containers/tfstate"
}

resource "azurerm_resource_group" "ci" {
  name     = "careroute-ci-rg"
  location = var.location
  tags     = local.tags
}

resource "azurerm_user_assigned_identity" "ci" {
  name                = "careroute-ci-id"
  location            = azurerm_resource_group.ci.location
  resource_group_name = azurerm_resource_group.ci.name
  tags                = local.tags
}

# Only workflow jobs running in the protected `production` environment get a
# token; pull requests and forks don't match this subject.
resource "azurerm_federated_identity_credential" "github_production" {
  name                      = "github-production"
  user_assigned_identity_id = azurerm_user_assigned_identity.ci.id
  issuer                    = "https://token.actions.githubusercontent.com"
  audience                  = ["api://AzureADTokenExchange"]
  subject                   = "repo:${var.github_repo}:environment:production"
}

resource "azurerm_role_assignment" "contributor" {
  scope                = data.azurerm_resource_group.app.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_user_assigned_identity.ci.principal_id
}

# Constrained delegation: the "Constrain roles" condition from Microsoft's
# examples, limited to the two Key Vault roles the main config assigns.
resource "azurerm_role_assignment" "rbac_admin_constrained" {
  scope                = data.azurerm_resource_group.app.id
  role_definition_name = "Role Based Access Control Administrator"
  principal_id         = azurerm_user_assigned_identity.ci.principal_id
  condition_version    = "2.0"
  condition            = "((!(ActionMatches{'Microsoft.Authorization/roleAssignments/write'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.assignable_roles}})) AND ((!(ActionMatches{'Microsoft.Authorization/roleAssignments/delete'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${local.assignable_roles}}))"
}

resource "azurerm_role_assignment" "state_container" {
  scope                = local.tfstate_container_id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.ci.principal_id
}
