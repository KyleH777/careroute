"""CareRoute API.

Endpoints are intentionally thin — enough to prove the database wiring works
end to end and to give the backup/restore drill something to verify against.
"""

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.models import (
    Facility,
    Patient,
    Provider,
    Referral,
    ReferralEvent,
    ReferralStatus,
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
)

app = FastAPI(title="CareRoute")


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
}


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Deliberately does not touch the database.

    The container HEALTHCHECK uses this, and a slow or busy database should
    not cause the orchestrator to kill an otherwise-healthy process.
    """
    return {"status": "ok"}


@app.get("/ready")
def ready(session: Session = Depends(get_session)) -> dict[str, str]:
    """Readiness probe: reports whether the database is actually reachable."""
    try:
        session.execute(select(1))
    except SQLAlchemyError as exc:
        return {
            "status": "degraded",
            "database": "unreachable",
            "detail": str(exc)[:200],
        }
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


@app.get("/referrals/worklist")
def worklist(
    limit: int = 20, session: Session = Depends(get_session)
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
    payload: PatientCreate, session: Session = Depends(get_session)
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
    payload: ReferralCreate, session: Session = Depends(get_session)
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
            actor=payload.actor,
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
            actor=payload.actor,
            note=payload.note,
        )
    )
    referral.status = payload.to_status
    session.commit()
    session.refresh(referral)
    return referral


@app.get("/referrals/{referral_id}", response_model=ReferralWithEvents)
def get_referral(
    referral_id: int, session: Session = Depends(get_session)
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
