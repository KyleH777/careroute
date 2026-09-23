"""CareRoute API.

Endpoints are intentionally thin — enough to prove the database wiring works
end to end and to give the backup/restore drill something to verify against.
"""

import logging

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import (
    READ_ROLES,
    ROUTING_ROLES,
    WRITE_ROLES,
    authenticate,
    create_access_token,
    get_current_user,
    require_role,
)
from app.config import settings
from app.db import get_session
from app.models import (
    Facility,
    Patient,
    Provider,
    Referral,
    ReferralEvent,
    ReferralStatus,
    User,
)
from app.referral_rules import (
    ReferralRuleViolation,
    validate_assignment,
    validate_transition,
)
from app.schemas import (
    PatientCreate,
    PatientOut,
    ReferralAssignRequest,
    ReferralCreate,
    ReferralEventOut,
    ReferralOut,
    ReferralStatusRequest,
    ReferralWithEvents,
    Token,
    UserOut,
)

app = FastAPI(title="CareRoute")
log = logging.getLogger("careroute")


@app.exception_handler(ReferralRuleViolation)
def handle_referral_rule_violation(
    request: Request, exc: ReferralRuleViolation
) -> JSONResponse:
    """Referral lifecycle rule violations (bad transition, bad assignment)
    are client errors, not server errors — map them to 409."""
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT, content={"detail": str(exc)}
    )


# Tables the /stats endpoint reports on, in dependency order.
_COUNTED = {
    "facilities": Facility,
    "providers": Provider,
    "patients": Patient,
    "referrals": Referral,
    "referral_events": ReferralEvent,
    "users": User,
}


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Deliberately does not touch the database.

    The container HEALTHCHECK uses this, and a slow or busy database should
    not cause the orchestrator to kill an otherwise-healthy process.
    """
    return {"status": "ok"}


@app.get("/ready")
def ready(
    response: Response, session: Session = Depends(get_session)
) -> dict[str, str]:
    """Readiness probe: 503 when the database is unreachable.

    Load balancers and orchestrators act on the status code, not the body,
    so "degraded" must be a non-2xx or traffic keeps flowing to an instance
    whose every real request will fail. The underlying error goes to the
    logs rather than this public response, since it can name internal hosts.
    """
    try:
        session.execute(select(1))
    except SQLAlchemyError as exc:
        log.warning("readiness check failed: database unreachable: %s", exc)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "degraded", "database": "unreachable"}
    return {"status": "ok", "database": "reachable", "env": settings.app_env}


@app.get("/stats")
def stats(session: Session = Depends(get_session)) -> dict[str, int]:
    """Row counts per table.

    The backup/restore drill compares this before and after a restore, so it
    is the cheapest way to confirm a restore actually brought the data back.
    """
    return {
        name: session.scalar(select(func.count()).select_from(model)) or 0
        for name, model in _COUNTED.items()
    }


@app.post("/auth/token", response_model=Token)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    session: Session = Depends(get_session),
) -> Token:
    """Exchange email + password for a bearer token (OAuth2 password flow).

    The form field is called `username` because the OAuth2 spec says so;
    CareRoute expects an email address in it.
    """
    user = authenticate(session, form.username, form.password)
    if user is None:
        # Same response for unknown email, wrong password, or inactive
        # account — don't tell a caller which emails exist.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return Token(
        access_token=create_access_token(user),
        expires_in=settings.jwt_ttl_minutes * 60,
    )


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    """Who the presented token belongs to."""
    return user


@app.get("/referrals/worklist")
def worklist(
    limit: int = 20,
    session: Session = Depends(get_session),
    _user: User = Depends(require_role(*READ_ROLES)),
) -> list[dict[str, object]]:
    """Open referrals, most urgent first, then oldest first.

    Backed by ix_referrals_status_priority_created.
    """
    rows = session.execute(
        select(Referral)
        .where(
            Referral.status.in_(
                [
                    ReferralStatus.SUBMITTED,
                    ReferralStatus.ACCEPTED,
                    ReferralStatus.SCHEDULED,
                ]
            )
        )
        .order_by(Referral.priority.desc(), Referral.created_at.asc())
        .limit(limit)
    ).scalars()

    return [
        {
            "id": r.id,
            "patient_id": r.patient_id,
            "specialty": r.specialty_requested,
            "status": r.status.value,
            "priority": r.priority.value,
            "assigned_provider_id": r.assigned_provider_id,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.post("/patients", response_model=PatientOut, status_code=status.HTTP_201_CREATED)
def create_patient(
    payload: PatientCreate,
    session: Session = Depends(get_session),
    _user: User = Depends(require_role(*WRITE_ROLES)),
) -> Patient:
    """Create a patient. 409s if the MRN is already in use."""
    patient = Patient(**payload.model_dump())
    session.add(patient)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"patient with mrn '{payload.mrn}' already exists",
        ) from exc
    session.refresh(patient)
    return patient


@app.post("/referrals", response_model=ReferralOut, status_code=status.HTTP_201_CREATED)
def create_referral(
    payload: ReferralCreate,
    session: Session = Depends(get_session),
    user: User = Depends(require_role(*WRITE_ROLES)),
) -> Referral:
    """Submit a new referral. Starts in DRAFT status; logs the first
    referral_event (from_status=null -> DRAFT)."""
    if session.get(Patient, payload.patient_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"patient {payload.patient_id} not found",
        )
    if session.get(Facility, payload.origin_facility_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"facility {payload.origin_facility_id} not found",
        )

    referral = Referral(
        patient_id=payload.patient_id,
        origin_facility_id=payload.origin_facility_id,
        specialty_requested=payload.specialty_requested,
        priority=payload.priority,
        reason=payload.reason,
        status=ReferralStatus.DRAFT,
    )
    session.add(referral)
    session.flush()  # assigns referral.id for the event below

    session.add(
        ReferralEvent(
            referral_id=referral.id,
            from_status=None,
            to_status=ReferralStatus.DRAFT,
            actor=user.email,
            note=payload.reason,
        )
    )
    session.commit()
    session.refresh(referral)
    return referral


@app.post("/referrals/{referral_id}/assign", response_model=ReferralOut)
def assign_referral(
    referral_id: int,
    payload: ReferralAssignRequest,
    session: Session = Depends(get_session),
    _user: User = Depends(require_role(*ROUTING_ROLES)),
) -> Referral:
    """Assign a provider to a referral. Validated by
    referral_rules.validate_assignment (status/specialty/capacity)."""
    referral = session.get(Referral, referral_id)
    if referral is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"referral {referral_id} not found",
        )
    provider = session.get(Provider, payload.provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"provider {payload.provider_id} not found",
        )

    validate_assignment(referral, provider)

    referral.assigned_provider_id = provider.id
    session.commit()
    session.refresh(referral)
    return referral


@app.post("/referrals/{referral_id}/status", response_model=ReferralOut)
def update_referral_status(
    referral_id: int,
    payload: ReferralStatusRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_role(*WRITE_ROLES)),
) -> Referral:
    """Transition a referral's status. Validated by
    referral_rules.validate_transition; logs a referral_event on success."""
    referral = session.get(Referral, referral_id)
    if referral is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"referral {referral_id} not found",
        )

    validate_transition(referral.status, payload.to_status)

    session.add(
        ReferralEvent(
            referral_id=referral.id,
            from_status=referral.status,
            to_status=payload.to_status,
            actor=user.email,
            note=payload.note,
        )
    )
    referral.status = payload.to_status
    session.commit()
    session.refresh(referral)
    return referral


@app.get("/referrals/{referral_id}", response_model=ReferralWithEvents)
def get_referral(
    referral_id: int,
    session: Session = Depends(get_session),
    _user: User = Depends(require_role(*READ_ROLES)),
) -> ReferralWithEvents:
    """Fetch a referral plus its full status-change history."""
    referral = session.get(Referral, referral_id)
    if referral is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"referral {referral_id} not found",
        )
    events = (
        session.execute(
            select(ReferralEvent)
            .where(ReferralEvent.referral_id == referral_id)
            .order_by(ReferralEvent.occurred_at)
        )
        .scalars()
        .all()
    )
    return ReferralWithEvents(
        **ReferralOut.model_validate(referral).model_dump(),
        events=[ReferralEventOut.model_validate(e) for e in events],
    )
