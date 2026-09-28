# Phase 4: Observability & Central Log Retention - Context

**Gathered:** 2026-09-28 · **Status:** Ready for planning

<decisions>
## Locked (user, 2026-09-28)
- Alert email: kileharrington@gmail.com. Supplied as `TF_VAR_alert_email` (local env + GitHub `production` env secret `TF_VAR_ALERT_EMAIL`), never committed to the public repo.
- Log Analytics retention: **90 days** (from 30). Ingestion cap stays 0.5 GB/day.
- Alert drill: stop Postgres briefly (~15 min, demo down), preceded by a free action-group test notification.

## Locked (design, cost-driven)
- **No availability probe.** A /ready ping would keep a replica warm (~0.5 vCPU 24/7, over budget, defeats scale-to-zero). Alerts instead:
  1. Log-search alert: API 5xx responses ≥ 5 in 5 min (from our JSON access lines).
  2. Log-search alert: any `/ready` 503 in 5 min.
  3. Metric alert: Postgres `is_db_alive` (Maximum) < 1. Fires even with zero traffic.
  All go to one action group (email). Expected cost ≈ $2-4/month.
- **Request logging**: pure ASGI middleware. `X-Request-ID` is accepted from the client if it matches `^[A-Za-z0-9._-]{8,64}$`, else a uuid4 is generated; it's echoed in the response header and held in a contextvar; one JSON line per request: `event=request, request_id, method, route (template), path (no query string, to keep query params out of logs), status, duration_ms`. All app logs are JSON via one formatter; uvicorn's access log is disabled (`--no-access-log`).
- **Audit events**: every ReferralEvent write also emits `event=audit` JSON (action, actor, referral_id, from/to status, request_id), with no patient data, so audit history survives in Log Analytics independently of the DB.
- **/metrics**: `prometheus_client`, served **only** on `METRICS_PORT` (9000) by a separate listener, never by the FastAPI app on 8000. Ingress maps only 8000, so the public URL can't reach it. Counter/histogram labelled by route template + method + status; gauges for SQLAlchemy pool (size, checked_out, overflow). Locally, Compose publishes 9000.
- Everything ships through the Phase 3 pipeline (CI applies alerts/retention).

## Claude's discretion
Metric names/buckets, log field order, test names.
</decisions>

<deferred>
- In-environment scraping by another app (needs Container Apps additionalPortMappings; not in azurerm 4.81). Revisit with a provider upgrade or a scraper.
- An uptime check for the zero-traffic case beyond `is_db_alive`.
</deferred>
