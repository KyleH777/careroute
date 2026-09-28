variable "location" {
  type    = string
  default = "centralus"
}

# GitHub issues this repo's OIDC subject in the immutable-ID form
# (owner@owner-id/repo@repo-id), not plain owner/repo; a name-only subject
# fails with AADSTS700213. The IDs also mean a renamed repo keeps working and
# a new repo reusing the name can't match.
variable "github_subject_repo" {
  description = "Repo part of the OIDC subject, as GitHub presents it: owner@id/repo@id."
  type        = string
  default     = "KyleH777@88053223/careroute@1383757448"
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
