# The API, plus one-shot jobs mirroring docker-compose.yml's pattern:
#
#   careroute-db-bootstrap  scripts/db_roles.py as the server admin: creates
#                           the least-privilege roles and syncs their
#                           passwords (ADR-0010). The only admin workload.
#   careroute-migrate       alembic upgrade head. Run before each release,
#                           the same role the `migrate` service plays locally.
#   careroute-seed          synthetic demo data + demo logins (--demo-deployment).
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

  # Stage B (var.db_roles_enabled) moves the jobs onto their own identities,
  # and migrate onto the schema-owner role (ADR-0010).
  migrate_identity = var.db_roles_enabled ? local.workload_identity.migrate : azurerm_user_assigned_identity.app
  migrate_env_secret = {
    DATABASE_URL = var.db_roles_enabled ? "database-url-migrate" : "database-url"
    JWT_SECRET   = "jwt-secret"
  }
  seed_identity = var.db_roles_enabled ? local.workload_identity.seed : azurerm_user_assigned_identity.app
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
      image  = var.app_image
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

  depends_on = [time_sleep.rbac_propagation, time_sleep.workload_rbac_propagation]
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
    identity_ids = [local.migrate_identity.id]
  }

  dynamic "secret" {
    for_each = { for k, v in local.kv_secret_ids : k => v if contains(values(local.migrate_env_secret), k) }
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = local.migrate_identity.id
    }
  }

  template {
    container {
      name    = "migrate"
      image   = var.migrate_image
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
        for_each = local.migrate_env_secret
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  tags = local.tags

  depends_on = [time_sleep.rbac_propagation, time_sleep.workload_rbac_propagation]
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
    identity_ids = [local.seed_identity.id]
  }

  # Needs the private demo passwords too: seed.py refuses a demo deployment
  # unless the write-capable logins get non-published passwords. Seeding is
  # plain INSERTs, so it runs as the DML-only app role.
  dynamic "secret" {
    for_each = { for k, v in local.kv_secret_ids : k => v if contains(local.workload_secrets.seed, k) }
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = local.seed_identity.id
    }
  }

  template {
    container {
      name    = "seed"
      image   = var.app_image
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

  depends_on = [time_sleep.rbac_propagation, time_sleep.workload_rbac_propagation]
}

resource "azurerm_container_app_job" "db_bootstrap" {
  name                         = "${local.name}-db-bootstrap"
  location                     = azurerm_resource_group.app.location
  resource_group_name          = azurerm_resource_group.app.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  workload_profile_name        = "Consumption"

  replica_timeout_in_seconds = 300
  replica_retry_limit        = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [local.workload_identity.dbbootstrap.id]
  }

  dynamic "secret" {
    for_each = { for k, v in local.kv_secret_ids : k => v if contains(local.workload_secrets.dbbootstrap, k) }
    content {
      name                = secret.key
      key_vault_secret_id = secret.value
      identity            = local.workload_identity.dbbootstrap.id
    }
  }

  template {
    container {
      name    = "db-bootstrap"
      image   = var.app_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "scripts/db_roles.py"]

      # No APP_ENV/JWT: db_roles.py doesn't import the app.
      dynamic "env" {
        for_each = {
          PYTHONUNBUFFERED = "1"
          MIGRATE_DB_ROLE  = local.db_role_migrate
          APP_DB_ROLE      = local.db_role_app
        }
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = {
          ADMIN_DATABASE_URL  = "database-url-admin"
          MIGRATE_DB_PASSWORD = "db-migrate-password"
          APP_DB_PASSWORD     = "db-app-password"
        }
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }

  tags = local.tags

  depends_on = [time_sleep.workload_rbac_propagation]
}
