# CareRoute infrastructure: the API on Azure Container Apps, Postgres Flexible
# Server on a private network, secrets in Key Vault.
#
# State is stored remotely in Azure Storage, created beforehand by
# backend-setup/setup-backend.sh (Terraform can't create the storage that
# holds its own state). First-time setup:
#
#   az login
#   ./backend-setup/setup-backend.sh
#   export ARM_SUBSCRIPTION_ID=$(az account show --query id -o tsv)
#   terraform init -backend-config=backend.hcl
#   export TF_VAR_operator_object_id=$(az ad signed-in-user show --query id -o tsv)
#   terraform apply -var app_image=<sha- image> -var migrate_image=<sha- image>
#
# The CI identity (infra/ci) must exist first; it is applied separately and
# only by a human. After the first deploy, CI applies this config on every
# push to main (ADR-0011); humans making infra-only changes pass the live
# images from `terraform output`. Never write plan files: they embed secrets.
#
# Resources are split by concern: network.tf, database.tf, keyvault.tf,
# containerapps.tf. Inputs in variables.tf, outputs in outputs.tf.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
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

# Subscription comes from ARM_SUBSCRIPTION_ID (azurerm v4 requires it to be
# explicit rather than silently using the CLI's current default).
provider "azurerm" {
  features {
    key_vault {
      # Destroying the vault soft-deletes it; don't also purge, so an
      # accidental destroy is recoverable for the retention period.
      purge_soft_delete_on_destroy = false
    }
  }
}

data "azurerm_client_config" "current" {}

locals {
  name = "careroute"
  tags = {
    project    = "careroute"
    managed-by = "terraform"
  }
}

# Short random suffix for names that must be globally unique (Key Vault).
resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  numeric = true
  special = false
}

resource "azurerm_resource_group" "app" {
  name     = "${local.name}-rg"
  location = var.location
  tags     = local.tags
}
