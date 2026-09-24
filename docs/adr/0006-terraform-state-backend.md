# ADR-0006: Terraform state in a separate, Entra-only storage account

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

Terraform state for the Azure deployment contains every generated secret, and must survive `terraform destroy` of the app. Terraform can't create the storage that holds its own state.

## Decision

State lives in Azure Storage bootstrapped by `infra/backend-setup/setup-backend.sh` (Azure CLI), in its own resource group `careroute-tfstate-rg`, separate from the app's `careroute-rg` (whose documented cleanup deletes the whole group). The account allows Entra ID auth only (shared keys disabled; verified refused), HTTPS/TLS 1.2, no public access, blob versioning with 30-day soft delete, and a CanNotDelete lock. The account name is subscription-derived and passed at init via `backend.hcl` (partial backend config) since backend blocks can't take variables.

## Consequences

- No storage keys exist to leak; access is governed by RBAC on the account.
- The state blob holds secrets: anyone with Storage Blob Data Reader on it can read them.
