# CareRoute infrastructure.
#
# Only the Terraform/backend configuration lives here so far. No resources are
# declared, so `terraform plan` will propose no changes.
#
# State is stored remotely in Azure Storage, created beforehand by
# backend-setup/setup-backend.sh (Terraform can't create the storage that
# holds its own state). First-time setup:
#
#   az login
#   ./backend-setup/setup-backend.sh
#   terraform init -backend-config=backend.hcl

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  backend "azurerm" {
    # Must match RESOURCE_GROUP and CONTAINER in backend-setup/setup-backend.sh.
    resource_group_name = "careroute-tfstate-rg"
    container_name      = "tfstate"
    key                 = "careroute.tfstate"

    # The storage account name is globally unique and differs per
    # subscription, and backend blocks can't reference variables, so it comes
    # from backend.hcl (written by the setup script) via
    # `terraform init -backend-config=backend.hcl`.

    # Authenticate to storage with your Entra ID login (az login) rather than
    # storage account keys; the setup script disables key access entirely.
    use_azuread_auth = true
  }
}
