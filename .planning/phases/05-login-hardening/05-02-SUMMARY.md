---
phase: 05-login-hardening
plan: 02
status: complete
requirements: [LOGIN-01, LOGIN-02]
completed: 2026-09-29
---
# 05-02 Summary
- infra: API env `TRUSTED_PROXY_HOPS=1` (plan: 1 in-place change).
- Pre-push scan **caught** the alert address (a live.com one) added to 04-02-SUMMARY → redacted before pushing (the scan now gates the push and checks only added lines).
- CI run 36587451501 (sha-37824f6): stage 1 → migrate `careroute-migrate-w7wrsll` ran `a6ca29d19c0c -> 5c1f0e7a9b21, add login_attempts` as careroute_migrate (the first real schema change through the pipeline) → stage 2 → active `careroute-api--0000007`. It also shipped de7bbd7 (DB connect timeout).
## Live evidence (drill email drill-1790694886@example.invalid, no real account)
- C1: attempts 1-5 → 401; the 6th → 429 `Retry-After: 897`; later 887, 876.
- C1 forged XFF: attempt 1 sent `X-Forwarded-For: 203.0.113.7` → recorded client_ip 45.62.14.183 (the operator's real IP from api.ipify.org).
- C2: after restarting `--0000007` (a new replica kpkl4 at 15:15:10) → still 429 (state in Postgres, shared by all replicas).
- C4: 8 rows (5 failure, 3 rate_limited) with email/IP/time/request_id, no password; the same 8 as `auth.login` in Log Analytics.
## Deviations
- The first restart attempt passed two active revision names (the old one was still draining) and failed; it was re-run against `--0000007` only.
