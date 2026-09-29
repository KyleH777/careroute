---
phase: 04-observability-central-log-retention
status: passed
verified: 2026-09-29
---

# Phase 4 Verification

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Request-ID header; one JSON line per request (id, method, path, status, latency); a Log Analytics query by ID returns it | PASS | Live header echo + LA query by `evidence-1790599063`; 11 tests |
| 2 | Prometheus /metrics (route/status counts+latency, DB pool) inside the env and locally; not on the public URL | PASS (with a noted deviation) | Public /metrics 404; :9000 unreachable externally; in-replica scrape works; local :9000. Other apps in the env can't scrape yet (azurerm lacks additionalPortMappings; ADR-0012) |
| 3 | The owner receives an Azure Monitor notification in a /ready-fail or 5xx drill; works with scale-to-zero; within budget | PASS (delivery partial) | All 3 alerts fired within 1-4 min and resolved; the action group executed 6×; the user received some emails. No availability probe, so scale-to-zero is kept; ≈$2-4/month |
| 4 | App + audit logs in LA with documented retention/cap, queryable after the revision is gone; runbook queries | PASS | 90 d / 0.5 GB; lines from 3 deleted revisions; live audit line for referral 190; 6 runbook queries run live |

Follow-ups: history rewrite for the leaked email (user decision); add a second alert receiver or fix mailbox filtering; push de7bbd7 (connect-timeout fix) so it deploys.
