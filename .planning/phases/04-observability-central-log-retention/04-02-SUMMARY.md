---
phase: 04-observability-central-log-retention
plan: 02
status: complete
requirements: [OBS-01, OBS-02, OBS-03, OBS-04]
completed: 2026-09-29
---

# 04-02 Summary

- Terraform: `monitoring.tf` (action group `careroute-owner`, log-search alerts `careroute-5xx-spike` / `careroute-ready-failing` at 5-min evaluation, metric alert `careroute-db-down` on `is_db_alive`); retention 30 → 90; API `METRICS_PORT=9000`; `alert_email` (sensitive, no default) via `TF_VAR_alert_email` / GitHub secret `TF_VAR_ALERT_EMAIL`.
- Deployed by CI run 36421874333 (sha-2093022): stage 1 "4 added, 3 changed", migrate Succeeded, stage 2 "3 changed", smoke active `careroute-api--0000005`.
- **Alert email changed to the owner's alert address (GitHub secret TF_VAR_ALERT_EMAIL)** at the user's request (GitHub secret updated before the deploy job started, so the action group was created with it; a local plan then showed no changes; the live receiver was confirmed).

## Evidence
- C1: `X-Request-ID: evidence-1790599063` echoed; Log Analytics by request_id → `/ready 200 5.08 ms` on `--0000005`.
- C2: public `/metrics` 404; port 9000 unreachable from outside; the in-replica scrape (`script -q /dev/null az containerapp exec ...`) returned `careroute_http_requests_total{method="GET",route="/ready",status="200"} 9.0` etc.
- C3 (drill, Postgres stopped ≈12:47 UTC 2026-09-28): `5xx-spike` fired 12:48:43, `ready-failing` 12:50:21, `db-down` 12:51:00; resolved 13:24 / 13:26 / 14:09. The alert history shows the action group executed for all 6 transitions. **The user received some, not all, emails** (delivery-side; the Azure side is confirmed).
- C4: retention 90 / cap 0.5 GB; lines from gone revisions (`--ronyo3p`, `--0000001`, `--0000002`) are queryable; live audit: referral 190 submitted→accepted by coordinator@careroute.demo (approved demo write), and the audit line is in Log Analytics with matching request_id.

## Deviations / incidents
1. **Owner email committed to the public repo**: my pre-push scan found the address in two .planning files, but the push wasn't gated on the scan. Redacted in de96fdc; it remains in pushed history (595ab32). History rewrite is pending the user's decision.
2. The action-group test notification is unavailable on this subscription ("Free subscription not supported"); only the real drill was run.
3. **The outage lasted ~1h20m, not ~15 min**: the operator machine slept mid-drill, delaying the Postgres restart (db-down resolved 14:09).
4. **The drill found a real bug**: `/ready` took a median 130 s (max ~18 min) to return 503 with the DB stopped (no connect timeout). Fixed in de7bbd7 (5 s `DB_CONNECT_TIMEOUT` + a test); it ships with the next push.
5. `az containerapp exec` needs a TTY; `script -q /dev/null` provides one.
