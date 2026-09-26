variable "location" {
  description = "Azure region for the app. Postgres Flexible Server is restricted for this subscription in eastus/eastus2/westus2; centralus is allowed."
  type        = string
  default     = "centralus"
}

variable "image" {
  description = "Container image to run. Pin to an immutable sha- tag published by CI, never :latest."
  type        = string
  default     = "ghcr.io/kyleh777/careroute:sha-da96d74"

  validation {
    condition     = !endswith(var.image, ":latest")
    error_message = "Pin an immutable sha- tag so every deploy is reproducible and rollback is a variable change."
  }
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
  default     = false
}

variable "legacy_vault_wide_app_access" {
  description = "Keep the pre-ADR-0010 vault-wide Key Vault Secrets User for the API identity. Set false once per-secret access is live (stage C)."
  type        = bool
  default     = true
}
