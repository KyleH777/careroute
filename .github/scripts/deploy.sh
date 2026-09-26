#!/usr/bin/env bash
# Ordered Azure deploy, called from the `deploy` job in ci.yml (ADR-0011).
#
#   deploy.sh apply <app_image> <migrate_image>   terraform apply, quietly
#   deploy.sh migrate [--simulate-failure]        run careroute-migrate, wait
#   deploy.sh smoke <image>                       /ready + images are <image>
#
# ADR-0001 order is the caller's: apply (migrate image only) → migrate →
# apply (app image) → smoke. Any failure exits non-zero and stops the job, so
# a failed migration never reaches the app.
#
# Terraform output is written to $RUNNER_TEMP and never printed in full or
# uploaded: only resource actions and errors are echoed (ADR-0006/0008).

set -euo pipefail

RG=careroute-rg
MIGRATE_JOB=careroute-migrate
LOGDIR="${RUNNER_TEMP:-/tmp}"

cd "$(dirname "$0")/../../infra"

# Azure's listSecrets calls, made while Terraform refreshes the Container
# App/Jobs, fail intermittently; an immediate retry has always succeeded.
TRANSIENT='(listing|retrieving) secrets for (Container App|Job)'

tf_apply() {
  local app_image=$1 migrate_image=$2 log attempt
  for attempt in 1 2; do
    log="$LOGDIR/apply-$(date +%s)-$attempt.log"
    if terraform apply -auto-approve -input=false -no-color \
         -var "app_image=$app_image" -var "migrate_image=$migrate_image" \
         >"$log" 2>&1; then
      grep -E ': (Creation|Modifications|Destruction) complete|^Apply complete' "$log" \
        | sed -E 's/ \[id=[^]]*\]//' || true
      return 0
    fi
    if [[ $attempt == 1 ]] && grep -qE "$TRANSIENT" "$log"; then
      echo "::warning::transient Azure secrets-read error during refresh; retrying once"
      continue
    fi
    echo "::error::terraform apply failed"
    grep -E -A5 '^Error:' "$log" | sed -E 's#/subscriptions/[0-9a-f-]+#/subscriptions/***#g' | head -40
    return 1
  done
}

run_migrate() {
  local exec_name status args=()
  if [[ ${1:-} == --simulate-failure ]]; then
    # Drill (DEPLOY-03): an override replaces the whole container, so image
    # and env are passed explicitly (AZURE.md → Querying the database).
    local image
    image=$(terraform output -raw migrate_image)
    echo "DRILL: running a migration that fails on purpose"
    args=(--container-name migrate --image "$image"
      --env-vars APP_ENV=production PYTHONUNBUFFERED=1
      DATABASE_URL=secretref:database-url-migrate JWT_SECRET=secretref:jwt-secret
      --command python --args "-craise SystemExit('drill: simulated migration failure')")
  fi

  exec_name=$(az containerapp job start -g "$RG" -n "$MIGRATE_JOB" "${args[@]}" --query name -o tsv)
  echo "migrate execution: $exec_name"

  local deadline=$((SECONDS + 720))
  while :; do
    status=$(az containerapp job execution show -g "$RG" -n "$MIGRATE_JOB" \
      --job-execution-name "$exec_name" --query properties.status -o tsv 2>/dev/null || true)
    case "$status" in
      Succeeded | Failed | Stopped | Degraded) break ;;
    esac
    ((SECONDS < deadline)) || { status=TimedOut; break; }
    sleep 10
  done
  echo "migrate execution $exec_name: $status"

  # Best effort: Alembic's own output (it never logs secrets).
  az containerapp job logs show -g "$RG" -n "$MIGRATE_JOB" --container migrate \
    --execution "$exec_name" --format text --tail 50 2>/dev/null | grep -E 'stdout|stderr' || true

  if [[ $status != Succeeded ]]; then
    echo "::error::migration $status; the app was NOT updated and the previous revision keeps serving"
    return 1
  fi
}

smoke() {
  local want=$1 url live_app live_migrate code i
  url=$(terraform output -raw api_url)
  for i in $(seq 1 10); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$url/ready" || true)
    [[ $code == 200 ]] && break
    echo "/ready -> $code (attempt $i)"
    sleep 15
  done
  [[ $code == 200 ]] || { echo "::error::/ready never returned 200"; return 1; }

  live_app=$(az containerapp show -g "$RG" -n careroute-api \
    --query 'properties.template.containers[0].image' -o tsv)
  live_migrate=$(az containerapp job show -g "$RG" -n "$MIGRATE_JOB" \
    --query 'properties.template.containers[0].image' -o tsv)
  echo "/ready 200; api image $live_app; migrate image $live_migrate"
  echo "active revision: $(az containerapp revision list -g "$RG" -n careroute-api \
    --query '[?properties.active].name' -o tsv)"
  [[ $live_app == "$want" && $live_migrate == "$want" ]] \
    || { echo "::error::live images don't match $want"; return 1; }
}

case "${1:-}" in
  apply) tf_apply "$2" "$3" ;;
  migrate) shift; run_migrate "$@" ;;
  smoke) smoke "$2" ;;
  *) echo "usage: deploy.sh apply|migrate|smoke ..." >&2; exit 2 ;;
esac
