---
phase: 05-login-hardening
status: passed
verified: 2026-09-29
---
# Phase 5 Verification
| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | 429 + Retry-After per IP and per account; succeeds again after the window; forged XFF doesn't bypass | PASS | Live: the 6th failure → 429 (Retry-After 897); a forged XFF recorded under the real IP. Tests: per-IP spray, window lift (back-dated rows), forged-XFF |
| 2 | Holds across replicas/restarts without a paid service | PASS | Postgres-backed; still 429 after a revision restart (new replica) |
| 3 | Below the limit, identical 401s with dummy-hash timing; existing tests pass | PASS | tests/test_auth.py unchanged and green; the limit is checked before verify, keyed on the email string; identical 429 for known/unknown |
| 4 | Every attempt recorded (email, IP, time, outcome; no password); runbook query | PASS | 8 live rows + 8 Log Analytics lines; password-absence tests; runbook queries run live |
