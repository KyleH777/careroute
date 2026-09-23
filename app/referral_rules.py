"""Referral lifecycle rules: the status transition state machine and
provider-assignment validation.

Pure functions — no FastAPI, no database session — so they can be tested
and reasoned about on their own. app/main.py is the only caller.
"""

from __future__ import annotations

from app.models import Provider, Referral, ReferralStatus


class ReferralRuleViolation(Exception):
    """Raised when a requested change violates a referral lifecycle rule."""


ALLOWED_TRANSITIONS: dict[ReferralStatus, set[ReferralStatus]] = {
    ReferralStatus.DRAFT: {ReferralStatus.SUBMITTED, ReferralStatus.CANCELLED},
    ReferralStatus.SUBMITTED: {
        ReferralStatus.ACCEPTED,
        ReferralStatus.REJECTED,
        ReferralStatus.CANCELLED,
    },
    ReferralStatus.ACCEPTED: {ReferralStatus.SCHEDULED, ReferralStatus.CANCELLED},
    ReferralStatus.SCHEDULED: {ReferralStatus.COMPLETED, ReferralStatus.CANCELLED},
    ReferralStatus.COMPLETED: set(),
    ReferralStatus.CANCELLED: set(),
    ReferralStatus.REJECTED: set(),
}

# Referral must be in one of these statuses before a provider can be
# assigned — not yet submitted (DRAFT) or already resolved (terminal).
ASSIGNABLE_STATUSES = {ReferralStatus.SUBMITTED, ReferralStatus.ACCEPTED}


def validate_transition(current: ReferralStatus, target: ReferralStatus) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ReferralRuleViolation(
            f"cannot transition referral from '{current.value}' to '{target.value}'"
        )


def validate_assignment(referral: Referral, provider: Provider) -> None:
    if referral.status not in ASSIGNABLE_STATUSES:
        raise ReferralRuleViolation(
            f"referral is not open for assignment (status='{referral.status.value}')"
        )
    if (
        provider.specialty.strip().lower()
        != referral.specialty_requested.strip().lower()
    ):
        raise ReferralRuleViolation(
            f"provider specialty '{provider.specialty}' does not match "
            f"requested specialty '{referral.specialty_requested}'"
        )
    if not provider.accepting_new_patients:
        raise ReferralRuleViolation(
            f"provider {provider.id} is not accepting new patients"
        )
