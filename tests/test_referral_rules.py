"""Unit tests for the referral lifecycle rules — pure functions, no HTTP
layer, no database writes required."""

import pytest

from app.models import Provider, Referral, ReferralPriority, ReferralStatus
from app.referral_rules import (
    ALLOWED_TRANSITIONS,
    ReferralRuleViolation,
    validate_assignment,
    validate_transition,
)


@pytest.mark.parametrize(
    "current,target",
    [
        (ReferralStatus.DRAFT, ReferralStatus.SUBMITTED),
        (ReferralStatus.DRAFT, ReferralStatus.CANCELLED),
        (ReferralStatus.SUBMITTED, ReferralStatus.ACCEPTED),
        (ReferralStatus.SUBMITTED, ReferralStatus.REJECTED),
        (ReferralStatus.SUBMITTED, ReferralStatus.CANCELLED),
        (ReferralStatus.ACCEPTED, ReferralStatus.SCHEDULED),
        (ReferralStatus.ACCEPTED, ReferralStatus.CANCELLED),
        (ReferralStatus.SCHEDULED, ReferralStatus.COMPLETED),
        (ReferralStatus.SCHEDULED, ReferralStatus.CANCELLED),
    ],
)
def test_valid_transitions_do_not_raise(current, target):
    validate_transition(current, target)


@pytest.mark.parametrize(
    "current,target",
    [
        (ReferralStatus.DRAFT, ReferralStatus.COMPLETED),
        (ReferralStatus.DRAFT, ReferralStatus.ACCEPTED),
        (ReferralStatus.SUBMITTED, ReferralStatus.SCHEDULED),
        (ReferralStatus.COMPLETED, ReferralStatus.SUBMITTED),
        (ReferralStatus.CANCELLED, ReferralStatus.DRAFT),
        (ReferralStatus.REJECTED, ReferralStatus.SUBMITTED),
    ],
)
def test_invalid_transitions_raise(current, target):
    with pytest.raises(ReferralRuleViolation):
        validate_transition(current, target)


def test_every_status_has_a_transition_entry():
    assert set(ALLOWED_TRANSITIONS.keys()) == set(ReferralStatus)


def _referral(status, specialty="Cardiology"):
    return Referral(
        id=1,
        patient_id=1,
        origin_facility_id=1,
        status=status,
        priority=ReferralPriority.ROUTINE,
        specialty_requested=specialty,
    )


def _provider(specialty="Cardiology", accepting=True):
    return Provider(
        id=1,
        facility_id=1,
        npi="1234567890",
        full_name="Dr. Test",
        specialty=specialty,
        accepting_new_patients=accepting,
    )


def test_validate_assignment_passes_for_open_matching_provider():
    validate_assignment(_referral(ReferralStatus.SUBMITTED), _provider())


def test_validate_assignment_rejects_wrong_status():
    with pytest.raises(ReferralRuleViolation):
        validate_assignment(_referral(ReferralStatus.DRAFT), _provider())


def test_validate_assignment_rejects_specialty_mismatch():
    with pytest.raises(ReferralRuleViolation):
        validate_assignment(
            _referral(ReferralStatus.SUBMITTED, specialty="Cardiology"),
            _provider(specialty="Neurology"),
        )


def test_validate_assignment_rejects_provider_not_accepting():
    with pytest.raises(ReferralRuleViolation):
        validate_assignment(
            _referral(ReferralStatus.SUBMITTED), _provider(accepting=False)
        )


def test_validate_assignment_specialty_match_is_case_insensitive():
    validate_assignment(
        _referral(ReferralStatus.SUBMITTED, specialty="cardiology"),
        _provider(specialty="CARDIOLOGY"),
    )
