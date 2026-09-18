"""Request/response models for the write endpoints.

Separate from app/models.py (the SQLAlchemy ORM layer): these describe the
HTTP contract, not the database schema. `Out` models read straight off ORM
instances via `from_attributes=True`.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models import ReferralPriority, ReferralStatus


class PatientCreate(BaseModel):
    mrn: str
    full_name: str
    date_of_birth: date
    phone: str | None = None
    email: str | None = None


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mrn: str
    full_name: str
    date_of_birth: date
    phone: str | None
    email: str | None
    created_at: datetime


class ReferralCreate(BaseModel):
    patient_id: int
    origin_facility_id: int
    specialty_requested: str
    priority: ReferralPriority = ReferralPriority.ROUTINE
    reason: str | None = None
    actor: str


class ReferralOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    patient_id: int
    origin_facility_id: int
    assigned_provider_id: int | None
    status: ReferralStatus
    priority: ReferralPriority
    specialty_requested: str
    reason: str | None
    created_at: datetime
    updated_at: datetime


class ReferralEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_status: ReferralStatus | None
    to_status: ReferralStatus
    actor: str
    note: str | None
    occurred_at: datetime


class ReferralWithEvents(ReferralOut):
    events: list[ReferralEventOut]


class ReferralAssignRequest(BaseModel):
    provider_id: int
    actor: str
    note: str | None = None


class ReferralStatusRequest(BaseModel):
    to_status: ReferralStatus
    actor: str
    note: str | None = None
