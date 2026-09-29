---
phase: 04-observability-central-log-retention
plan: 03
status: complete
requirements: [OBS-01, OBS-02, OBS-03, OBS-04]
completed: 2026-09-29
---

# 04-03 Summary
- ADR-0012 (alerting without availability probes; blind spot; metrics port; deferred in-env scraping); index updated.
- AZURE.md "Logs, metrics and alerts": JSON schema, Log Analytics usage, 90 d / 0.5 GB, metrics scrape, alert table, drill result; TF_VAR_alert_email in the manual-apply instructions.
- RUNBOOK: "Log queries" (6 KQL, all run live 2026-09-29 with real placeholders: 2/1/5/1/1/84 rows) and "When an alert fires".
- INCIDENT-RESPONSE: alert emails count as detection; evidence retention 90 d; the audit trail's second copy in Log Analytics; the "no monitoring" / "no central log retention" gaps are replaced by the zero-traffic blind spot.
- README: observability bullet.
