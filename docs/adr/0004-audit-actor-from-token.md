# ADR-0004: Audit trail actor comes from the authenticated identity

- **Status:** Accepted
- **Date:** 2026-09-23

## Context

`referral_events` records who changed a referral's status. Originally clients sent a free-text `actor` field, so anyone could attribute a change to someone else.

## Decision

Request bodies carry no `actor`; `referral_events.actor` is set to the authenticated user's email. An `actor` sent anyway is ignored (Pydantic drops unknown fields). A test submits a spoofed actor and asserts the real identity is recorded.

## Consequences

- The audit trail is trustworthy for status changes.
- Known gaps, listed in INCIDENT-RESPONSE.md: reads are not logged (can't scope what a compromised account viewed) and provider assignment is not logged.
