"""Authentication (tokens, login) and authorization (the role matrix)."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from pydantic import ValidationError

from app.config import DEV_JWT_SECRET, Settings, settings
from app.models import ReferralEvent, UserRole
from tests.conftest import TEST_PASSWORD

# --- login -----------------------------------------------------------------


def test_login_returns_token_that_identifies_the_user(anon_client, make_user):
    user = make_user(UserRole.CLINICIAN)

    response = anon_client.post(
        "/auth/token", data={"username": user.email, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.jwt_ttl_minutes * 60

    me = anon_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json() == {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": "clinician",
    }


def test_login_email_is_case_insensitive(anon_client, make_user):
    user = make_user(UserRole.VIEWER)
    response = anon_client.post(
        "/auth/token",
        data={"username": user.email.upper(), "password": TEST_PASSWORD},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("email", "password", "active"),
    [
        ("viewer@test.careroute", "wrong-password", True),
        ("nobody@test.careroute", TEST_PASSWORD, True),
        ("viewer@test.careroute", TEST_PASSWORD, False),
    ],
    ids=["wrong-password", "unknown-email", "inactive-account"],
)
def test_login_failures_are_indistinguishable(
    anon_client, make_user, email, password, active
):
    make_user(UserRole.VIEWER, is_active=active)
    response = anon_client.post(
        "/auth/token", data={"username": email, "password": password}
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "incorrect email or password"}


# --- token validation ------------------------------------------------------


def _token(user_id: int, *, secret: str | None = None, **overrides) -> str:
    now = datetime.now(UTC)
    claims = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=5)}
    claims.update(overrides)
    return jwt.encode(claims, secret or settings.jwt_secret, algorithm="HS256")


def test_missing_token_is_401(anon_client):
    response = anon_client.get("/referrals/worklist")
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "make_token",
    [
        lambda uid: "not-a-jwt",
        lambda uid: _token(uid, exp=datetime.now(UTC) - timedelta(seconds=1)),
        lambda uid: _token(uid, secret="some-other-secret-at-least-32-bytes-long"),
        lambda uid: _token(999_999),
    ],
    ids=["garbage", "expired", "wrong-signature", "unknown-user"],
)
def test_bad_tokens_are_401(anon_client, make_user, make_token):
    user = make_user(UserRole.COORDINATOR)
    response = anon_client.get(
        "/referrals/worklist",
        headers={"Authorization": f"Bearer {make_token(user.id)}"},
    )
    assert response.status_code == 401


def test_deactivating_a_user_revokes_their_existing_token(anon_client, make_user, db):
    user = make_user(UserRole.COORDINATOR)
    headers = {"Authorization": f"Bearer {_token(user.id)}"}
    assert anon_client.get("/referrals/worklist", headers=headers).status_code == 200

    user.is_active = False
    db.commit()

    assert anon_client.get("/referrals/worklist", headers=headers).status_code == 401


# --- role matrix -----------------------------------------------------------


def _new_patient(n: int) -> dict[str, str]:
    return {"mrn": f"MRN-RBAC-{n}", "full_name": "RBAC", "date_of_birth": "1990-01-01"}


def test_viewer_can_read_but_not_write(client_as, submitted_referral):
    viewer = client_as(UserRole.VIEWER)

    assert viewer.get("/referrals/worklist").status_code == 200
    assert viewer.get(f"/referrals/{submitted_referral.id}").status_code == 200

    response = viewer.post("/patients", json=_new_patient(1))
    assert response.status_code == 403
    assert response.json() == {"detail": "role 'viewer' may not perform this action"}
    response = viewer.post(
        f"/referrals/{submitted_referral.id}/status", json={"to_status": "accepted"}
    )
    assert response.status_code == 403


def test_clinician_can_write_but_not_assign(client_as, submitted_referral, provider):
    clinician = client_as(UserRole.CLINICIAN)

    assert clinician.post("/patients", json=_new_patient(2)).status_code == 201
    response = clinician.post(
        f"/referrals/{submitted_referral.id}/status", json={"to_status": "accepted"}
    )
    assert response.status_code == 200

    response = clinician.post(
        f"/referrals/{submitted_referral.id}/assign",
        json={"provider_id": provider.id},
    )
    assert response.status_code == 403


def test_coordinator_can_assign(client_as, submitted_referral, provider):
    response = client_as(UserRole.COORDINATOR).post(
        f"/referrals/{submitted_referral.id}/assign",
        json={"provider_id": provider.id},
    )
    assert response.status_code == 200


def test_ops_endpoints_stay_public(anon_client):
    assert anon_client.get("/health").status_code == 200
    assert anon_client.get("/ready").status_code == 200
    assert anon_client.get("/stats").status_code == 200


# --- audit trail -----------------------------------------------------------


def test_actor_comes_from_token_not_request_body(client_as, submitted_referral, db):
    clinician = client_as(UserRole.CLINICIAN)

    response = clinician.post(
        f"/referrals/{submitted_referral.id}/status",
        json={"to_status": "accepted", "actor": "someone-else"},
    )
    assert response.status_code == 200

    event = db.query(ReferralEvent).filter_by(referral_id=submitted_referral.id).one()
    assert event.actor == "clinician@test.careroute"


# --- configuration ---------------------------------------------------------


def test_default_jwt_secret_refused_outside_dev():
    with pytest.raises(ValidationError, match="JWT_SECRET must be set"):
        Settings(app_env="production", jwt_secret=DEV_JWT_SECRET)

    assert Settings(app_env="production", jwt_secret="x" * 48).app_env == "production"
    # Every dev environment the Compose files use accepts the default.
    for env in ("local", "dev", "test"):
        assert Settings(app_env=env, jwt_secret=DEV_JWT_SECRET).app_env == env
