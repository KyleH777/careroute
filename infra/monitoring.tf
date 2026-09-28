# Alerts (ADR-0012). No availability probe: pinging /ready every few minutes
# would keep a replica warm around the clock (~0.5 vCPU 24/7), which breaks
# the ~$20/month budget and scale-to-zero. Instead:
#
#   careroute-5xx-spike      >= 5 API 5xx responses in 5 min (from our JSON
#                            access lines)
#   careroute-ready-failing  any /ready 503 in 5 min (DB unreachable while
#                            traffic or probes are hitting a replica)
#   careroute-db-down        Postgres is_db_alive < 1: fires even with zero
#                            traffic
#
# Blind spot, accepted: with no traffic at all and the database healthy, an
# app that can't start isn't noticed until the next request.

resource "azurerm_monitor_action_group" "owner" {
  name                = "${local.name}-owner"
  resource_group_name = azurerm_resource_group.app.name
  short_name          = "careroute"
  tags                = local.tags

  email_receiver {
    name                    = "owner"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }
}

locals {
  # One place for the access-line parsing both log alerts share.
  api_requests_kql = <<-KQL
    ContainerAppConsoleLogs_CL
    | where ContainerAppName_s == "careroute-api"
    | extend e = parse_json(Log_s)
    | where tostring(e.event) == "request"
  KQL

  log_alerts = {
    "5xx-spike" = {
      description = "The API returned 5 or more 5xx responses in 5 minutes."
      severity    = 2
      where       = "toint(e.status) >= 500"
      threshold   = 5
    }
    "ready-failing" = {
      description = "/ready returned 503: the API can't reach the database."
      severity    = 1
      where       = "tostring(e.route) == \"/ready\" and toint(e.status) == 503"
      threshold   = 1
    }
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "api" {
  for_each                = local.log_alerts
  name                    = "${local.name}-${each.key}"
  resource_group_name     = azurerm_resource_group.app.name
  location                = azurerm_resource_group.app.location
  description             = each.value.description
  severity                = each.value.severity
  scopes                  = [azurerm_log_analytics_workspace.main.id]
  evaluation_frequency    = "PT5M"
  window_duration         = "PT5M"
  enabled                 = true
  auto_mitigation_enabled = true
  tags                    = local.tags

  criteria {
    query                   = "${local.api_requests_kql}| where ${each.value.where}\n| summarize n = count()"
    time_aggregation_method = "Total"
    metric_measure_column   = "n"
    operator                = "GreaterThanOrEqual"
    threshold               = each.value.threshold

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.owner.id]
  }
}

resource "azurerm_monitor_metric_alert" "db_down" {
  name                = "${local.name}-db-down"
  resource_group_name = azurerm_resource_group.app.name
  scopes              = [azurerm_postgresql_flexible_server.main.id]
  description         = "Postgres reports is_db_alive < 1: the database is down or stopped."
  severity            = 0
  frequency           = "PT1M"
  window_size         = "PT5M"
  auto_mitigate       = true
  tags                = local.tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "is_db_alive"
    aggregation      = "Maximum"
    operator         = "LessThan"
    threshold        = 1
  }

  action {
    action_group_id = azurerm_monitor_action_group.owner.id
  }
}
