# ADR-0002: Separate liveness and readiness probes

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

A database outage should stop traffic to the API, but must not make the orchestrator restart healthy API processes (restarts can't fix a database). An earlier `/ready` returned HTTP 200 with a "degraded" body during an outage, so load balancers kept routing to an instance whose every request failed.

## Decision

`/health` (liveness) never touches the database and always returns 200 while the process is alive. `/ready` (readiness) runs `SELECT 1` and returns **503** when the database is unreachable, logging the underlying error rather than returning it (the endpoint is public). Container HEALTHCHECK and Container Apps liveness use `/health`; Container Apps readiness uses `/ready`.

## Consequences

- "Container healthy" does not mean "service working"; the runbook tells on-call to check `/ready`.
- With the DB down, `/ready` 503s and ingress stops routing; the API recovers on its own when the DB returns (`pool_pre_ping`), verified by drill.
