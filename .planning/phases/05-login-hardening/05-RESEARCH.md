# Phase 5 Research
- ADR-0003 timing equalization lives in `app/auth.authenticate` (dummy Argon2 hash). The rate-limit check must happen in the route **before** `authenticate`, keyed by email string, so it adds no account-existence signal.
- Container Apps ingress is Envoy: it appends the connecting peer to `X-Forwarded-For`. The rightmost entry is the only one Envoy vouches for. To confirm live at execution: send `X-Forwarded-For: 203.0.113.7` and check the recorded client_ip equals the operator's public IP (`curl -s https://api.ipify.org`), not 203.0.113.7.
- uvicorn's own proxy-header handling trusts only 127.0.0.1 by default, so `scope["client"]` is Envoy's address. The app parses XFF itself (explicit hop count, testable).
- New table → Alembic migration (as careroute_migrate). App DML via default privileges, already guarded by `tests/test_db_roles.py`, which parametrizes over every model table. The CI deploy runs the migration before the app rolls (ADR-0001/0011).
