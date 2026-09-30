"""The record_access table (ADR-0014): constraints, no FKs, seed-reset survival."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import RecordAccess
from tests.conftest import owner_engine

_spec = importlib.util.spec_from_file_location(
    "seed", Path(__file__).resolve().parents[1] / "scripts" / "seed.py"
)
assert _spec and _spec.loader
seed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(seed)


def test_app_can_insert_and_read_row(db, submitted_referral, patient):
    row = RecordAccess(
        actor="a@test.careroute",
        action="referral.read",
        referral_id=submitted_referral.id,
        patient_id=patient.id,
    )
    db.add(row)
    db.commit()
    assert row.id is not None
    assert row.occurred_at is not None
    assert row.request_id is None
    assert db.query(RecordAccess).count() == 1


def test_unknown_action_rejected(db, patient):
    db.add(RecordAccess(actor="a@x", action="referral.delete", patient_id=patient.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_row_needs_a_target(db):
    db.add(RecordAccess(actor="a@x", action="referral.list"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_rows_survive_referral_delete(db, submitted_referral, patient):
    rid, pid = submitted_referral.id, patient.id
    db.add(
        RecordAccess(
            actor="a@x", action="referral.read", referral_id=rid, patient_id=pid
        )
    )
    db.commit()
    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM referral_events WHERE referral_id = :id"), {"id": rid}
        )
        conn.execute(text("DELETE FROM referrals WHERE id = :id"), {"id": rid})
    db.expire_all()
    rows = db.query(RecordAccess).all()
    assert [r.referral_id for r in rows] == [rid]


def test_seed_reset_keeps_record_access(db, patient):
    db.add(RecordAccess(actor="a@x", action="patient.create", patient_id=patient.id))
    db.commit()
    with Session(owner_engine) as owner:
        seed.reset(owner)
        owner.commit()
        count = owner.execute(text("select count(*) from record_access")).scalar_one()
    assert count == 1
