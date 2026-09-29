# ADR-0013: Login rate limiting and attempt log in Postgres

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

`/auth/token` is on the public internet. Nothing limited guessing, and nothing recorded failed attempts, so password spraying was both free and invisible. The API runs 0-2 replicas and scales to zero, so an in-memory limiter would reset on every cold start and differ per replica. The budget rules out a paid cache.

## Decision

- **One table, two jobs.** `login_attempts` (email as submitted and lower-cased, client IP, outcome `success`/`failure`/`rate_limited`, time, request ID; never the password) is both the evidence log and the limiter's counter. Every attempt also emits an `auth.login` audit line to Log Analytics (ADR-0012).
- **Limits:** ≤ 5 failures per email and ≤ 20 failures per client IP in a sliding 15-minute window (settings `LOGIN_*`). Only failures count, so a user who logs in often is never limited, and hammering while limited doesn't extend the window. The window uses the database clock, so replicas agree.
- **Check before verify.** The limit is evaluated before the password: a limited caller gets `429 {"detail":"too many login attempts; try again later"}` with `Retry-After` (seconds until the oldest counted failure ages out), keyed on the submitted email string. Known and unknown emails get the identical 429, and no Argon2 work is spent. Below the limit the three 401 cases are unchanged (ADR-0003).
- **Client IP behind ingress.** Container Apps' Envoy appends the connecting peer to `X-Forwarded-For`. With `TRUSTED_PROXY_HOPS=1` (Azure) the app uses only that rightmost entry; entries a client forges sit to its left and are ignored. Locally it's 0 (the socket peer). A non-IP value is stored as NULL, and that attempt skips the per-IP check.

## Consequences

- Verified live 2026-09-29: the 6th failure for one email → 429 with `Retry-After: 897`; still 429 after an API revision restart (a new replica); a login with a forged `X-Forwarded-For: 203.0.113.7` was recorded under the caller's real IP.
- **Accepted: account lockout as denial of service.** Anyone can block logins for a known email for up to 15 minutes by failing it 5 times. It's bounded by the window, and an operator can lift it early (RUNBOOK → Login attempts).
- **Accepted: burst overshoot.** Count-then-insert isn't atomic across replicas, so a concurrent burst can get a few attempts past the limit. That doesn't change brute-force economics.
- **Accepted: growth.** Every attempt is a row, rate-limited ones included, so an attack grows the table. There is no automatic pruning yet; the runbook has a manual prune.
- Shared NAT (an office behind one IP) shares the 20-failure IP budget. Raise `LOGIN_MAX_FAILURES_PER_IP` if that becomes a problem.
