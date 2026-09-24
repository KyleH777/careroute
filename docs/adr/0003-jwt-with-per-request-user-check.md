# ADR-0003: JWT bearer auth with a per-request user re-check

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

The API needs authentication and three roles (viewer, clinician, coordinator). Pure stateless JWTs can't be revoked before expiry; server-side sessions need a shared store.

## Decision

OAuth2 password flow issues short-lived (60 min) HS256 JWTs. Passwords are argon2id-hashed. On every request the user is re-loaded from the database and `is_active`/`role` are taken from the database, not the token. Login returns an identical 401 for unknown email, wrong password and inactive account, and verifies against a dummy hash for unknown emails so timing matches. The app refuses to start outside local/dev/test with the built-in dev `JWT_SECRET`.

## Consequences

- Deactivation and demotion take effect on the next request (verified live). Cost: one primary-key lookup per request.
- Rotating `JWT_SECRET` invalidates every token at once, which is the emergency lever in the incident process.
- Not yet done: rate limiting and failed-login logging on `/auth/token`, refresh tokens, and RS256 if other services must verify tokens.
