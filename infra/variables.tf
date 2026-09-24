variable "location" {
  description = "Azure region for the app. Postgres Flexible Server is restricted for this subscription in eastus/eastus2/westus2; centralus is allowed."
  type        = string
  default     = "centralus"
}

variable "image" {
  description = "Container image to run. Pin to an immutable sha- tag published by CI, never :latest."
  type        = string
  default     = "ghcr.io/kyleh777/careroute:sha-e15d28f"

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
