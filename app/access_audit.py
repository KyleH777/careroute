"""PHI access auditing: who touched which record, and when (ADR-0014).

Every route that returns or changes referral/patient data calls stage() before
its commit, so the record_access rows share the route's transaction: if the
audit insert fails the request fails closed (500) and nothing is persisted.
emit() is called after the commit, so no log line describes something that did
not persist.

The actor is always the authenticated user's email (ADR-0004), never anything
from the request. Rows and log lines carry IDs only, never names, MRN, DOB or
free text.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.models import RECORD_ACCESS_ACTIONS, RecordAccess
from app.observability import audit, request_id_var

ACTIONS: frozenset[str] = frozenset(RECORD_ACCESS_ACTIONS)

# (referral_id, patient_id)
Pair = tuple[int | None, int | None]

F = TypeVar("F", bound=Callable[..., Any])


def audited(action: str) -> Callable[[F], F]:
    """Mark a route endpoint as auditing `action` (checked by the route test)."""
    if action not in ACTIONS:
        raise ValueError(f"unknown audit action {action!r}")

    def decorator(fn: F) -> F:
        setattr(fn, "__audit_action__", action)  # noqa: B010
        return fn

    return decorator


def stage(
    session: Session,
    actor: str,
    action: str,
    pairs: Sequence[Pair],
    *,
    old_provider_id: int | None = None,
    new_provider_id: int | None = None,
) -> None:
    """Add one record_access row per pair to the session's transaction.

    Never commits; the caller's commit persists the rows together with the
    change. Does nothing when `pairs` is empty.
    """
    if not pairs:
        return
    request_id = request_id_var.get()
    rows = [
        {
            "actor": actor,
            "action": action,
            "referral_id": referral_id,
            "patient_id": patient_id,
            "old_provider_id": old_provider_id,
            "new_provider_id": new_provider_id,
            "request_id": request_id,
        }
        for referral_id, patient_id in pairs
    ]
    session.execute(insert(RecordAccess), rows)


def emit(actor: str, action: str, pairs: Sequence[Pair], **extra: int | None) -> None:
    """Write the single ID-only audit log line for a request (after commit)."""
    audit(
        action,
        actor=actor,
        referral_ids=sorted({r for r, _ in pairs if r is not None}),
        patient_ids=sorted({p for _, p in pairs if p is not None}),
        **extra,
    )
