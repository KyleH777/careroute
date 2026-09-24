# ADR-0009: Public demo exposes only a read-only login

- **Status:** Accepted
- **Date:** 2026-09-24

## Context

Reviewers should be able to try the live demo, but a published password that can write data invites junk data and abuse, and the seed script previously refused to run outside development at all.

## Decision

The seed runs outside local/dev/test only with `--demo-deployment`. Then only `viewer@careroute.demo` gets the published password; clinician and coordinator get private passwords from `DEMO_CLINICIAN_PASSWORD`/`DEMO_COORDINATOR_PASSWORD` (Key Vault, min 16 chars, never the published value), and `--reset` is refused. The policy is a pure function with its own tests.

## Consequences

- Anyone can browse the demo; only the owner can demonstrate writes.
- `/auth/token` is internet-facing without rate limiting, so private passwords are long and random; rate limiting is open work.
