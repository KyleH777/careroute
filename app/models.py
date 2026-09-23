"""CareRoute domain models.

The care-routing problem in five tables: patients are referred out of an
origin facility, a referral is routed to a provider, and every status change
is appended to an immutable event log.

These models are the single source of truth for the schema. Never edit the
database by hand — change a model, then run:

    docker compose exec api alembic revision --autogenerate -m "describe it"
    docker compose exec api alembic upgrade head
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ReferralStatus(str, enum.Enum):
    """Lifecycle of a referral. Terminal states: COMPLETED, CANCELLED, REJECTED."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class ReferralPriority(str, enum.Enum):
    """Clinical urgency, which drives routing order."""

    ROUTINE = "routine"
    URGENT = "urgent"
    EMERGENT = "emergent"


# Shared Enum type objects. `referral_status` is used by three columns across
# two tables; reusing one instance is what makes SQLAlchemy and Alembic emit a
# single CREATE TYPE instead of one per column.
#
# values_callable stores the lowercase member *values* ("submitted") rather
# than SQLAlchemy's default of member *names* ("SUBMITTED"), so what psql and
# a pg_dump show matches what the API emits and accepts.
REFERRAL_STATUS = Enum(
    ReferralStatus,
    name="referral_status",
    native_enum=True,
    values_callable=lambda cls: [m.value for m in cls],
)
REFERRAL_PRIORITY = Enum(
    ReferralPriority,
    name="referral_priority",
    native_enum=True,
    values_callable=lambda cls: [m.value for m in cls],
)


class Facility(Base):
    """A clinic or hospital that originates or receives referrals."""

    __tablename__ = "facilities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    providers: Mapped[list[Provider]] = relationship(back_populates="facility")

    __table_args__ = (Index("ix_facilities_state_city", "state", "city"),)


class Provider(Base):
    """A clinician who can accept referrals."""

    __tablename__ = "providers"

    id: Mapped[int] = mapped_column(primary_key=True)
    facility_id: Mapped[int] = mapped_column(
        ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    # National Provider Identifier: exactly 10 digits, unique per clinician.
    npi: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    specialty: Mapped[str] = mapped_column(String(100), nullable=False)
    accepting_new_patients: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    facility: Mapped[Facility] = relationship(back_populates="providers")
    referrals: Mapped[list[Referral]] = relationship(back_populates="assigned_provider")

    __table_args__ = (
        CheckConstraint("npi ~ '^[0-9]{10}$'", name="ck_providers_npi_10_digits"),
        Index(
            "ix_providers_specialty_accepting", "specialty", "accepting_new_patients"
        ),
    )


class Patient(Base):
    """A person being referred. MRN is the external medical record number."""

    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(primary_key=True)
    mrn: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    referrals: Mapped[list[Referral]] = relationship(back_populates="patient")


class Referral(Base):
    """A routing request moving a patient from an origin facility to a provider."""

    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    origin_facility_id: Mapped[int] = mapped_column(
        ForeignKey("facilities.id", ondelete="RESTRICT"), nullable=False
    )
    # Null until the routing engine assigns someone.
    assigned_provider_id: Mapped[int | None] = mapped_column(
        ForeignKey("providers.id", ondelete="SET NULL")
    )
    status: Mapped[ReferralStatus] = mapped_column(
        REFERRAL_STATUS, nullable=False, default=ReferralStatus.DRAFT
    )
    priority: Mapped[ReferralPriority] = mapped_column(
        REFERRAL_PRIORITY, nullable=False, default=ReferralPriority.ROUTINE
    )
    specialty_requested: Mapped[str] = mapped_column(String(100), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    patient: Mapped[Patient] = relationship(back_populates="referrals")
    assigned_provider: Mapped[Provider | None] = relationship(
        back_populates="referrals"
    )
    events: Mapped[list[ReferralEvent]] = relationship(
        back_populates="referral", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # The routing worklist query: open referrals by priority, oldest first.
        Index(
            "ix_referrals_status_priority_created", "status", "priority", "created_at"
        ),
        Index("ix_referrals_patient", "patient_id"),
    )


class ReferralEvent(Base):
    """Append-only audit trail of referral status transitions."""

    __tablename__ = "referral_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    referral_id: Mapped[int] = mapped_column(
        ForeignKey("referrals.id", ondelete="CASCADE"), nullable=False
    )
    # Null on the first event, when the referral is created.
    from_status: Mapped[ReferralStatus | None] = mapped_column(REFERRAL_STATUS)
    to_status: Mapped[ReferralStatus] = mapped_column(REFERRAL_STATUS, nullable=False)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    referral: Mapped[Referral] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_referral_events_referral_time", "referral_id", "occurred_at"),
    )
