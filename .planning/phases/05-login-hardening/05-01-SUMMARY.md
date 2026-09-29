---
phase: 05-login-hardening
plan: 01
status: complete
requirements: [LOGIN-01, LOGIN-02]
completed: 2026-09-29
---
# 05-01 Summary
- `LoginAttempt` model + `login_outcome` enum; migration `5c1f0e7a9b21` (indexes (email, occurred_at), (client_ip, occurred_at); explicit DROP TYPE in downgrade). `alembic check`: no drift; round-trip OK.
- `app/login_guard.py`: `client_ip()` (TRUSTED_PROXY_HOPS; rightmost XFF; ipaddress-validated; non-IP → None), `check()` (a single SQL query per key using the DB clock: count of the most recent `limit` failures in the window + seconds until the oldest ages out), `record()` (row + `auth.login` audit line).
- `/auth/token`: normalize email → check → 429 + Retry-After (records rate_limited) → authenticate → record success/failure → existing 401/token.
- conftest truncates login_attempts. 13 new tests (per-email, window lift via back-dating, successes don't count, case-insensitive, identical 429s, per-IP spray, forged XFF ignored, malformed/untrusted XFF, recording without the password in rows or logs, audit lines). Full suite 133 passed; test_auth.py unchanged and green; test_db_roles covers the new table.
## Deviations
- The first implementation mixed a Python datetime with an SQL interval (500s in tests); rewritten as one SQL query evaluated on the DB clock.
