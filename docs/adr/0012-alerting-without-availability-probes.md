# ADR-0012: Alerting from logs and a database metric, not availability probes

- **Status:** Accepted
- **Date:** 2026-09-28

## Context

The owner had no way to learn that the live demo was broken, and logs disappeared with the replica that wrote them. The demo runs on a ~$20/month budget with the API scaled to zero when idle. The usual answer, an availability test hitting `/ready` every few minutes, would wake the API on every probe and keep a replica running around the clock (about 0.5 vCPU / 1 GiB continuously). That costs more than the budget and quietly turns scale-to-zero off.

## Decision

- **Every request is traceable.** Each response carries `X-Request-ID` (a well-formed inbound value is kept, otherwise a uuid4). The API writes one JSON line per request (`event=request`: route template, path without query string, status, duration) and one JSON line per referral change (`event=audit`: action, actor, referral, from/to status, no free text). Container logs go to Log Analytics, kept **90 days** with a **0.5 GB/day** ingestion cap.
- **Three alerts, one email action group** (the owner's address comes from `TF_VAR_alert_email`, never the repo):
  - `careroute-5xx-spike`: log-search alert, ≥ 5 API 5xx responses in 5 minutes.
  - `careroute-ready-failing`: log-search alert, any `/ready` 503 in 5 minutes.
  - `careroute-db-down`: metric alert on Postgres `is_db_alive` < 1, which fires even with no traffic.
- **Metrics on a port ingress never maps.** Prometheus metrics (per-route request count/latency, DB pool gauges) are served only on `METRICS_PORT` (9000) by a separate listener. The public URL can't reach them; the owner scrapes from inside the replica (`az containerapp exec`).

## Consequences

- Cost stays at a few dollars a month (two 5-minute log alerts, one metric alert, free email), and scale-to-zero keeps working.
- **Blind spot, accepted:** with no traffic and a healthy database, an API that can't start goes unnoticed until the next request. `is_db_alive` covers the most likely outage; the rest waits for a user.
- Log-based alerts depend on ingestion. Past the daily cap, logs, and therefore these two alerts, stop until the next day. The DB metric alert doesn't depend on logs.
- Log alerts evaluate every 5 minutes on data that arrives a few minutes late, so expect roughly 5-15 minutes from failure to email.
- Scraping metrics from another app in the environment needs Container Apps additional port mappings, which azurerm 4.81 doesn't support. Deferred.
- The audit trail now exists twice (the `referral_events` table and Log Analytics), so it survives a database restore.
