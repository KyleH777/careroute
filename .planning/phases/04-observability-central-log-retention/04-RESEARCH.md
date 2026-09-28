# Phase 4 Research (free sources)

| Question | Finding |
|---|---|
| Internal-only extra port on the Container App? | `azurerm_container_app.ingress` in 4.81 has only cors / ip_security_restriction / traffic_weight blocks, **no additional_port_mappings**. An azapi patch would fight azurerm's PUT on every deploy. → metrics on an unmapped port: unreachable publicly; scrape in-replica via `az containerapp exec` |
| Log alert resource | `azurerm_monitor_scheduled_query_rules_alert_v2` available |
| DB liveness metric | `is_db_alive` exists on the server (aggregation Maximum) |
| Availability probe vs scale-to-zero | A probe every few minutes keeps a replica active (cooldown), ~0.5 vCPU/1 GiB around the clock, over the ~$20 budget. Rejected |
| Log table | Console output → `ContainerAppConsoleLogs_CL` (`Log_s`, `ContainerAppName_s`, `RevisionName_s`); parse with `parse_json(Log_s)` |

To confirm at execution: `prometheus-client` latest version (pin it); whether `az containerapp exec --command` works non-interactively for the in-replica scrape; log-alert pricing tier for a 5-min frequency.
