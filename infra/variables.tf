variable "location" {
  description = "Azure region for the app. Postgres Flexible Server is restricted for this subscription in eastus/eastus2/westus2; centralus is allowed."
  type        = string
  default     = "centralus"
}

# Images. No defaults on purpose: every apply must say which image each part
# runs, so a forgotten -var fails instead of silently rolling back. Deploys
# (CI, ADR-0011) set migrate_image first, run the migration, and only then
# move app_image (ADR-0001). For infra-only changes, pass the live values:
#
#   terraform apply -var app_image=$(terraform output -raw app_image) \
#                   -var migrate_image=$(terraform output -raw migrate_image)
variable "app_image" {
  description = "Image for the API, the seed job and the db-bootstrap job. An immutable sha- tag, never :latest."
  type        = string

  validation {
    condition     = !endswith(var.app_image, ":latest")
    error_message = "Pin an immutable sha- tag so every deploy is reproducible and rollback is a variable change."
  }
}

variable "migrate_image" {
  description = "Image for the careroute-migrate job. Moves ahead of app_image during a deploy (ADR-0001)."
  type        = string

  validation {
    condition     = !endswith(var.migrate_image, ":latest")
    error_message = "Pin an immutable sha- tag so every deploy is reproducible and rollback is a variable change."
  }
}

# Key Vault Secrets Officer goes to a fixed set of principals, not to "whoever
# runs Terraform": otherwise the first CI apply would take it from the human
# operator. Supplied via TF_VAR_operator_object_id (az ad signed-in-user show
# --query id -o tsv), so no personal ID is committed.
variable "operator_object_id" {
  description = "Entra object ID of the human operator who keeps Key Vault Secrets Officer."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.operator_object_id))
    error_message = "operator_object_id must be an Entra object ID (GUID)."
  }
}

variable "ci_identity_name" {
  description = "The CI deploy identity (created by infra/ci, ADR-0011)."
  type        = string
  default     = "careroute-ci-id"
}

variable "ci_resource_group" {
  type    = string
  default = "careroute-ci-rg"
}

variable "postgres_sku" {
  description = "Postgres Flexible Server SKU. B_Standard_B1ms is the one covered by Azure's 12-month free offer."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "api_min_replicas" {
  description = "0 = scale to zero when idle (near-zero cost, a few seconds' cold start on the first request)."
  type        = number
  default     = 0
}

variable "api_max_replicas" {
  type    = number
  default = 2
}

# Least-privilege rollout (ADR-0010), in stages so no single apply can break
# the live API:
#   A  db_roles_enabled = false  add role passwords, secrets, identities and
#                                the db-bootstrap job; run it. Nothing live
#                                changes credentials.
#   B  db_roles_enabled = true   API/seed use careroute_app, migrate uses
#                                careroute_migrate, each on its own identity.
#   C  legacy_vault_wide_app_access = false
#                                drop the API identity's vault-wide read.
variable "db_roles_enabled" {
  description = "Switch workloads to the least-privilege Postgres roles and per-workload identities (stage B). Run careroute-db-bootstrap first."
  type        = bool
  default     = true
}

variable "legacy_vault_wide_app_access" {
  description = "Keep the pre-ADR-0010 vault-wide Key Vault Secrets User for the API identity. Set false once per-secret access is live (stage C)."
  type        = bool
  default     = false
}
