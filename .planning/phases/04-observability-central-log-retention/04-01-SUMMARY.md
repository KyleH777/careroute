---
phase: 04-observability-central-log-retention
plan: 01
status: complete
requirements: [OBS-01, OBS-02, OBS-04]
completed: 2026-09-28
---

# 04-01 Summary

- `app/observability.py`: JsonFormatter + a log-record factory that stamps request_id at record creation; `configure_logging()` (root + uvicorn to JSON; uvicorn.access disabled, since it duplicated our line and added the client IP); `RequestContextMiddleware` (pure ASGI: X-Request-ID validation `^[A-Za-z0-9._-]{8,64}$` else uuid4, one `careroute.access` JSON line, route template via route matching, unhandled errors → 500 JSON + header + a JSON traceback on `careroute.error`); `audit()` → `careroute.audit` `event=audit`; a private Prometheus registry (`careroute_http_requests_total`, `careroute_http_request_duration_seconds`, `careroute_db_pool_{size,checked_out,overflow}`); `start_metrics_server()` on METRICS_PORT only.
- main.py: lifespan starts metrics; audits `referral.created` and `referral.status_changed` (actor, referral_id, from/to; no note/reason text).
- prometheus-client 0.26.0; Dockerfile `--no-access-log`; Compose api METRICS_PORT 9000 (dev-published).
- Tests: `tests/test_observability.py` (11). Red = collection error (no module); green = full suite 117 passed. ruff/format/mypy clean.
- Real-image smoke (throwaway project, alt ports): X-Request-ID present; API `/metrics` 404; the metrics port serves the series; 0 non-JSON log lines; uvicorn.access lines 0 after the fix.

## Deviations
- Found in the smoke test: `configure_logging` re-enabled uvicorn's access logger (which uvicorn had silenced), so it's now explicitly disabled.
- The request ID is stamped by a record factory instead of being read at format time (formatting can happen after the contextvar is reset).
