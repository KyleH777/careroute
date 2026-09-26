variable "location" {
  type    = string
  default = "centralus"
}

variable "github_repo" {
  description = "owner/repo whose production environment may deploy."
  type        = string
  default     = "KyleH777/careroute"
}

variable "app_resource_group" {
  type    = string
  default = "careroute-rg"
}

variable "state_storage_account" {
  description = "Terraform state storage account (same value as ../backend.hcl)."
  type        = string
  default     = "stcareroutetf3a2fe1"
}
