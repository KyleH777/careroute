# The API, plus two one-shot jobs mirroring docker-compose.yml's pattern:
#
#   careroute-migrate   alembic upgrade head. Run before each release,
#                       the same role the `migrate` service plays locally.
#   careroute-seed      synthetic demo data + demo logins (--demo-deployment).
#
# Jobs are manual-trigger, so `terraform apply` never runs them implicitly:
#
#   az containerapp job start -g careroute-rg -n careroute-migrate

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${local.name}-logs"
  location            = azurerm_resource_group.app.location
  resource_group_name = azurerm_resource_group.app.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.5 # hard cost cap: ingestion stops past 0.5 GB/day
  tags                = local.tags
}

resource "azurerm_container_app_environment" "main" {
  name                       = "${local.name}-env"
  location                   = azurerm_resource_group.app.location
  resource_group_name        = azurerm_resource_group.app.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  infrastructure_subnet_id = azurerm_subnet.apps.id
  # Azure creates a managed resource group for the environment's plumbing;
  # naming it avoids a random name and plan drift.
  infrastructure_resource_group_name = "${local.name}-env-infra-rg"

  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
  }

  tags = local.tags
}

locals {
  # Key Vault-backed Container App secrets. versionless_id means a rotated
  # secret is picked up on the next revision/restart without a Terraform change.
  kv_secret_ids = { for k, s in azurerm_key_vault_secret.app : k => s.versionless_id }

  # Everything the app process needs, for both the API and the jobs.
  app_env_plain = {
    APP_ENV          = "production"
    PYTHONUNBUFFERED = "1"
  }
  app_env_secret = {
    DATABASE_URL = "database-url"
    JWT_SECRET   = "jwt-secret"
  }
}

resource "azurerm_container_app" "api" {
  name                         = "${local.name}-api"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.app.name
  revision_mode                = "Single"
  workload_profile_name        = "Consumption"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  dynamic "secret" {
    for_each = { for k, v in local.kv_secret_ids : k => v if contains(values(local.app_env_secret), k) }
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = var.api_min_replicas
    max_replicas = var.api_max_replicas

    container {
      name   = "api"
      image  = var.image
      cpu    = 0.5
      memory = "1Gi"

      dynamic "env" {
        for_each = local.app_env_plain
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.app_env_secret
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      # Same split as local: liveness never touches the DB (a DB outage must
      # not restart healthy replicas); readiness 503s without the DB, so
      # ingress stops routing to a replica that can't serve.
      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/health"
      }
      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/ready"
      }
    }
  }

  tags = local.tags

  depends_on = [time_sleep.rbac_propagation]
}

resource "azurerm_container_app_job" "migrate" {
  name                         = "${local.name}-migrate"
  location                     = azurerm_resource_group.app.location
  resource_group_name          = azurerm_resource_group.app.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"

  replica_timeout_in_seconds = 600
  replica_retry_limit        = 0 # a failed migration needs a human, not a retry

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  dynamic "secret" {
    for_each = { for k, v in local.kv_secret_ids : k => v if contains(values(local.app_env_secret), k) }
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  template {
    container {
      name    = "migrate"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["alembic", "upgrade", "head"]

      dynamic "env" {
        for_each = local.app_env_plain
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.app_env_secret
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  tags = local.tags

  depends_on = [time_sleep.rbac_propagation]
}

resource "azurerm_container_app_job" "seed" {
  name                         = "${local.name}-seed"
  location                     = azurerm_resource_group.app.location
  resource_group_name          = azurerm_resource_group.app.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"

  replica_timeout_in_seconds = 600
  replica_retry_limit        = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  # Needs the private demo passwords too: seed.py refuses a demo deployment
  # unless the write-capable logins get non-published passwords.
  dynamic "secret" {
    for_each = local.kv_secret_ids
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  template {
    container {
      name    = "seed"
      image   = var.image
      cpu     = 0.5
      memory  = "1Gi"
      command = ["python", "scripts/seed.py", "--demo-deployment"]

      dynamic "env" {
        for_each = local.app_env_plain
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = merge(local.app_env_secret, {
          DEMO_CLINICIAN_PASSWORD   = "demo-clinician-password"
          DEMO_COORDINATOR_PASSWORD = "demo-coordinator-password"
        })
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  tags = local.tags

  depends_on = [time_sleep.rbac_propagation]
}
