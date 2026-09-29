# Phase 5: Login Hardening - Context
**Gathered:** 2026-09-29 · **Status:** Ready for planning

<decisions>
## Locked (design; no user decision was needed)
- **Store = Postgres** (`login_attempts` table): works across replicas and scale-to-zero, with no paid cache. The same table is the LOGIN-02 evidence log.
- Columns: id, occurred_at (timestamptz, default now), email (lower-cased as submitted, ≤ 254 chars), client_ip (INET), outcome enum (`success`, `failure`, `rate_limited`), request_id. **Never** the password. Indexes: (email, occurred_at), (client_ip, occurred_at).
- **Limits** (settings, env-overridable): ≤ 5 failures per email and ≤ 20 failures per client IP in a sliding 15-minute window. Only `failure` rows count (a legitimate user logging in repeatedly is never limited; a limited caller can't extend the window by hammering).
- **Check before verify:** if either limit is exceeded → 429 `{"detail": "too many login attempts; try again later"}` with `Retry-After` = seconds until the oldest counted failure leaves the window (at least 1). The Argon2 verify is skipped, keyed on the submitted email string, so known and unknown emails behave identically. The attempt is recorded as `rate_limited`.
- **Below the limit, unchanged:** unknown email / wrong password / inactive → the identical 401 with dummy-hash timing (ADR-0003); the existing tests must keep passing.
- **Client IP:** `TRUSTED_PROXY_HOPS` (default 0 = use the socket peer, for Compose/tests). On Azure = 1: take the rightmost `X-Forwarded-For` entry, which Envoy appends from the real peer; anything a client forges sits to the left and is ignored. Invalid/missing → fall back to the socket peer.
- Every attempt also emits `event=audit action=auth.login` (email, client_ip, outcome; no password), so login evidence reaches Log Analytics (Phase 4) too.

## Accepted trade-offs (document in ADR-0013)
- Per-account limiting lets anyone lock an account out for ≤ 15 min by failing its logins (the classic trade-off; bounded by the window).
- The count-then-insert is not atomic across replicas: a burst can overshoot the limit by a few attempts. Acceptable for brute-force economics.
- The table grows with attacks (every attempt, incl. rate_limited, is a row). No automatic pruning in this phase; the runbook gets a manual prune query. Revisit if needed.

## Claude's discretion
Module layout, test names, exact query shapes.
</decisions>
