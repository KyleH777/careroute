#!/usr/bin/env bash
# Bootstrap the Azure Storage backend that holds CareRoute's Terraform state.
#
# This is plain Azure CLI, not Terraform, on purpose: Terraform can't create
# the storage its own state lives in (the classic chicken-and-egg). Run this
# once per subscription, then `terraform init` in infra/.
#
#   az login
#   ./infra/backend-setup/setup-backend.sh            # asks before changing anything
#   ./infra/backend-setup/setup-backend.sh --yes      # no prompt
#
# Safe to re-run: every step checks for what already exists first.
#
# Creates (all in its own resource group, deliberately separate from the app's
# careroute-rg, so tearing the app down can never delete the state):
#
#   resource group    careroute-tfstate-rg
#   storage account   stcareroutetf<6 hex chars from the subscription ID>
#   blob container    tfstate
#
# ...then writes infra/backend.hcl with the storage account name for
# `terraform init -backend-config=backend.hcl`.
#
# Security posture of the storage account:
#   - Entra ID (Azure AD) auth only: shared-key access is disabled, so there
#     are no storage account keys to leak. Terraform authenticates as you
#     (use_azuread_auth = true in main.tf).
#   - HTTPS only, TLS 1.2 minimum, no anonymous/public blob access.
#   - Blob versioning + 30-day soft delete for blobs and containers, so a
#     corrupted or deleted state file can be recovered.
#   - A CanNotDelete lock on the storage account.
#
# Permissions needed: Owner (or Contributor + User Access Administrator) on the
# subscription. The script grants *you* "Storage Blob Data Contributor" on the
# storage account and creates a resource lock, and both require role-assignment
# rights. Must be run as a user (`az login`), not a service principal.
#
# Cost: one Standard_LRS storage account holding a few KB of state, which is
# pennies per month.
#
# Every setting can be overridden with an environment variable, e.g.:
#   LOCATION=westus2 ./infra/backend-setup/setup-backend.sh

set -euo pipefail

# --- configuration (keep RESOURCE_GROUP / CONTAINER in sync with main.tf) ---
RESOURCE_GROUP="${RESOURCE_GROUP:-careroute-tfstate-rg}"
LOCATION="${LOCATION:-eastus}"
CONTAINER="${CONTAINER:-tfstate}"
STORAGE_SKU="${STORAGE_SKU:-Standard_LRS}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TAGS=(project=careroute purpose=terraform-state managed-by=setup-backend.sh)

INFRA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_HCL="${INFRA_DIR}/backend.hcl"

assume_yes=false
[[ "${1:-}" == "--yes" ]] && assume_yes=true

log()  { printf '==> %s\n' "$*"; }
skip() { printf '    already exists: %s\n' "$*"; }
die()  { printf '!! %s\n' "$*" >&2; exit 1; }

# --- preflight ---------------------------------------------------------------

command -v az >/dev/null || die "Azure CLI not found. Install: brew install azure-cli"

az account show >/dev/null 2>&1 || die "Not logged in. Run: az login"

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
SUBSCRIPTION_NAME="$(az account show --query name -o tsv)"

[[ "$(az account show --query user.type -o tsv)" == "user" ]] \
  || die "Logged in as a service principal. Run this as a user (az login)."

# Storage account names are globally unique across all of Azure: 3-24 chars,
# lowercase letters and digits only. A suffix derived from the subscription
# ID keeps the name unique yet stable, so re-runs find the same account.
suffix="$(printf '%s' "$SUBSCRIPTION_ID" | shasum -a 256 | cut -c1-6)"
STORAGE_ACCOUNT="${STORAGE_ACCOUNT:-stcareroutetf${suffix}}"

[[ "$STORAGE_ACCOUNT" =~ ^[a-z0-9]{3,24}$ ]] \
  || die "Invalid storage account name '${STORAGE_ACCOUNT}' (3-24 lowercase letters/digits)"

cat <<EOF

Terraform state backend
  Subscription     ${SUBSCRIPTION_NAME} (${SUBSCRIPTION_ID})
  Resource group   ${RESOURCE_GROUP}
  Location         ${LOCATION}
  Storage account  ${STORAGE_ACCOUNT}  (${STORAGE_SKU})
  Container        ${CONTAINER}
  Writes           ${BACKEND_HCL}

EOF

if [[ "$assume_yes" != true ]]; then
  read -r -p "Create these in the subscription above? [y/N] " answer
  [[ "$answer" =~ ^[Yy]$ ]] || { echo "Aborted. Nothing was changed."; exit 1; }
fi

# --- 1. resource group -------------------------------------------------------

if [[ "$(az group exists --name "$RESOURCE_GROUP")" == "true" ]]; then
  skip "resource group ${RESOURCE_GROUP}"
else
  log "Creating resource group ${RESOURCE_GROUP}"
  az group create \
    --name "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --tags "${TAGS[@]}" \
    --output none
fi

# --- 2. storage account ------------------------------------------------------

if az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  skip "storage account ${STORAGE_ACCOUNT}"
else
  available="$(az storage account check-name --name "$STORAGE_ACCOUNT" --query nameAvailable -o tsv)"
  [[ "$available" == "true" ]] || die "Storage account name '${STORAGE_ACCOUNT}' is taken elsewhere in Azure. Re-run with STORAGE_ACCOUNT=<another-name>."

  log "Creating storage account ${STORAGE_ACCOUNT} (this takes ~30s)"
  az storage account create \
    --name "$STORAGE_ACCOUNT" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --sku "$STORAGE_SKU" \
    --kind StorageV2 \
    --https-only true \
    --min-tls-version TLS1_2 \
    --allow-blob-public-access false \
    --allow-shared-key-access false \
    --tags "${TAGS[@]}" \
    --output none
fi

STORAGE_ID="$(az storage account show --name "$STORAGE_ACCOUNT" --resource-group "$RESOURCE_GROUP" --query id -o tsv)"

# Versioning keeps every prior state file; soft delete recovers deleted blobs
# and containers. Idempotent, so it's always applied.
log "Enabling blob versioning and ${RETENTION_DAYS}-day soft delete"
az storage account blob-service-properties update \
  --account-name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --enable-versioning true \
  --enable-delete-retention true \
  --delete-retention-days "$RETENTION_DAYS" \
  --enable-container-delete-retention true \
  --container-delete-retention-days "$RETENTION_DAYS" \
  --output none

# --- 3. data-plane access for you --------------------------------------------
# Shared keys are disabled, so reading/writing blobs needs an Entra ID role.

USER_OBJECT_ID="$(az ad signed-in-user show --query id -o tsv)"
ROLE="Storage Blob Data Contributor"

existing="$(az role assignment list \
  --assignee "$USER_OBJECT_ID" --role "$ROLE" --scope "$STORAGE_ID" \
  --query 'length(@)' -o tsv)"
if [[ "$existing" != "0" ]]; then
  skip "role '${ROLE}' for you on ${STORAGE_ACCOUNT}"
else
  log "Granting you '${ROLE}' on ${STORAGE_ACCOUNT}"
  az role assignment create \
    --assignee-object-id "$USER_OBJECT_ID" \
    --assignee-principal-type User \
    --role "$ROLE" \
    --scope "$STORAGE_ID" \
    --output none
fi

# --- 4. blob container -------------------------------------------------------
# A brand-new role assignment can take a few minutes to propagate, so retry.

container_exists() {
  [[ "$(az storage container exists --name "$CONTAINER" --account-name "$STORAGE_ACCOUNT" \
        --auth-mode login --query exists -o tsv 2>/dev/null)" == "true" ]]
}

if container_exists; then
  skip "container ${CONTAINER}"
else
  log "Creating container ${CONTAINER} (retries while the role assignment propagates)"
  for attempt in $(seq 1 20); do
    if az storage container create --name "$CONTAINER" --account-name "$STORAGE_ACCOUNT" \
         --auth-mode login --public-access off --output none 2>/dev/null; then
      break
    fi
    [[ $attempt -eq 20 ]] && die "Could not create the container after ~5 minutes. The role assignment may still be propagating: wait a few minutes and re-run."
    printf '    not yet authorized (attempt %d/20), waiting 15s...\n' "$attempt"
    sleep 15
  done
  container_exists || die "Container ${CONTAINER} still not visible after creation."
fi

# --- 5. delete lock ----------------------------------------------------------
# Applied last so it can't get in the way of the steps above on a re-run.

LOCK_NAME="do-not-delete-terraform-state"
if az lock show --name "$LOCK_NAME" --resource-group "$RESOURCE_GROUP" \
     --resource "$STORAGE_ACCOUNT" --resource-type Microsoft.Storage/storageAccounts >/dev/null 2>&1; then
  skip "delete lock on ${STORAGE_ACCOUNT}"
else
  log "Adding CanNotDelete lock to ${STORAGE_ACCOUNT}"
  az lock create \
    --name "$LOCK_NAME" \
    --lock-type CanNotDelete \
    --resource-group "$RESOURCE_GROUP" \
    --resource "$STORAGE_ACCOUNT" \
    --resource-type Microsoft.Storage/storageAccounts \
    --notes "Holds Terraform state for CareRoute. Remove deliberately, never as cleanup." \
    --output none
fi

# --- 6. hand the storage account name to Terraform ---------------------------
# Backend blocks can't use variables, and the account name differs per
# subscription, so it's passed at init time (partial backend configuration).
# Names only, no secrets, so this file is safe to commit.

cat > "$BACKEND_HCL" <<EOF
# Generated by infra/backend-setup/setup-backend.sh; re-run it to regenerate.
# Used with: terraform init -backend-config=backend.hcl
storage_account_name = "${STORAGE_ACCOUNT}"
EOF

cat <<EOF

Done. Terraform state backend is ready.

  Storage account  ${STORAGE_ACCOUNT}
  Container        ${CONTAINER}
  Wrote            ${BACKEND_HCL}

Next:
  cd infra
  terraform init -backend-config=backend.hcl
EOF
