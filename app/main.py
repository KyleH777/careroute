"""CareRoute API.

Endpoints are intentionally thin — enough to prove the database wiring works
end to end and to give the backup/restore drill something to verify against.
"""

from fastapi import Depends, FastAPI, HTTPException, status
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
from app.schemas import PatientCreate, PatientOut

app = FastAPI(title="CareRoute")

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
        return {"status": "degraded", "database": "unreachable", "detail": str(exc)[:200]}
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
