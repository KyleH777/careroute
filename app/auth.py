"""Authentication and role-based authorization.

Staff log in with email + password (OAuth2 password flow) and receive a
short-lived HS256 JWT. Every protected endpoint depends on `require_role`,
which decodes the token, loads the user, and checks their role.

Permission map:

    viewer       read referrals and the worklist
    clinician    + create patients, submit referrals, change referral status
    coordinator  + assign providers to referrals
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import User, UserRole

_ALGORITHM = "HS256"
_hasher = PasswordHasher()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# A real-looking hash to verify against when the email doesn't exist, so a
# login for an unknown user costs the same time as a wrong password and
# response timing doesn't reveal which emails have accounts.
_DUMMY_HASH = _hasher.hash("timing-equalizer")

READ_ROLES = (UserRole.VIEWER, UserRole.CLINICIAN, UserRole.COORDINATOR)
WRITE_ROLES = (UserRole.CLINICIAN, UserRole.COORDINATOR)
ROUTING_ROLES = (UserRole.COORDINATOR,)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def authenticate(session: Session, email: str, password: str) -> User | None:
    """Return the active user with these credentials, or None."""
    user = session.scalar(select(User).where(User.email == email.lower()))
    try:
        _hasher.verify(user.password_hash if user else _DUMMY_HASH, password)
    except (VerifyMismatchError, InvalidHashError):
        return None
    if user is None or not user.is_active:
        return None
    return user


def create_access_token(user: User) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(user.id),
        "role": user.role.value,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_ttl_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=_ALGORITHM)


_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="invalid or expired token",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme), session: Session = Depends(get_session)
) -> User:
    """Decode the bearer token and load its user. 401 on anything amiss.

    The role is re-read from the database rather than trusted from the token,
    so a deactivated or demoted account loses access immediately instead of
    when its token expires.
    """
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        user_id = int(claims["sub"])
    except (jwt.PyJWTError, ValueError):
        raise _UNAUTHORIZED from None

    user = session.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


def require_role(*roles: UserRole) -> Callable[..., User]:
    """Dependency factory: the current user, if their role is in `roles`."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role '{user.role.value}' may not perform this action",
            )
        return user

    return dependency
