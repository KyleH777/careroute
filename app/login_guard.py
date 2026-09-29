"""Login rate limiting and the login-attempt log (ADR-0013).

Checked before the password is verified, keyed on the submitted email and the
client IP, so a limited caller gets the same 429 whether or not the account
exists and costs no Argon2 work. Only failures count: a user logging in often
is never limited. The window is evaluated with the database clock so every
replica agrees.
"""

from __future__ import annotations

import ipaddress

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import LoginAttempt, LoginOutcome
from app.observability import audit, request_id_var


def _as_ip(value: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address((value or "").strip()))
    except ValueError:
        return None


def client_ip(request: Request) -> str | None:
    """The caller's IP: the entry `trusted_proxy_hops` from the right of
    X-Forwarded-For, else the socket peer. None if neither is an IP."""
    hops = settings.trusted_proxy_hops
    if hops > 0:
        entries = [
            e
            for e in request.headers.get("x-forwarded-for", "").split(",")
            if e.strip()
        ]
        if len(entries) >= hops:
            ip = _as_ip(entries[-hops])
            if ip:
                return ip
    return _as_ip(request.client.host if request.client else None)


_WINDOW_SQL = """
    select count(*) as n,
           extract(epoch from min(occurred_at)
                   + make_interval(secs => :window) - now()) as wait
    from (
        select occurred_at from login_attempts
        where {column} = {value} and outcome = 'failure'
          and occurred_at > now() - make_interval(secs => :window)
        order by occurred_at desc
        limit :limit
    ) recent
"""


def _retry_after(session: Session, column: str, value: str, limit: int) -> int | None:
    """Seconds until the key drops back under `limit` failures, or None.

    Uses the database clock, so every replica sees the same window.
    """
    cast = "cast(:value as inet)" if column == "client_ip" else ":value"
    n, wait = session.execute(
        text(_WINDOW_SQL.format(column=column, value=cast)),
        {"value": value, "window": settings.login_window_seconds, "limit": limit},
    ).one()
    if n < limit:
        return None
    # The limit-th most recent failure has to age out before a new attempt.
    return max(1, int(float(wait or 0)) + 1)


def check(session: Session, email: str, ip: str | None) -> int | None:
    """None if the attempt may proceed, else the Retry-After seconds."""
    waits = [
        _retry_after(session, "email", email, settings.login_max_failures_per_email)
    ]
    if ip is not None:
        waits.append(
            _retry_after(session, "client_ip", ip, settings.login_max_failures_per_ip)
        )
    blocked = [w for w in waits if w is not None]
    return max(blocked) if blocked else None


def record(session: Session, email: str, ip: str | None, outcome: LoginOutcome) -> None:
    """Persist the attempt (never the password) and emit an audit line."""
    request_id = request_id_var.get()
    session.add(
        LoginAttempt(email=email, client_ip=ip, outcome=outcome, request_id=request_id)
    )
    session.commit()
    audit("auth.login", email=email, client_ip=ip, outcome=outcome.value)
