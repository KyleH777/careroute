"""The record_access queries in docs/RUNBOOK.md, executed against the test DB.

RUNBOOK_SQL holds the exact text pasted into the runbook's `sql "..."` calls
(plain string literals only, so a host-side check can literal_eval them and
confirm each appears verbatim in the runbook). The tests run them through
sqlalchemy text() exactly like the runbook's sql() helper.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db import engine
from app.models import RecordAccess
from tests.conftest import owner_engine

RUNBOOK_SQL = {
    "patient_window": "select occurred_at, actor, action, referral_id, request_id from record_access where patient_id = <patient-id> and occurred_at between timestamptz '<T1>' and timestamptz '<T2>' order by occurred_at",
    "referral_window": "select occurred_at, actor, action, patient_id, request_id from record_access where referral_id = <referral-id> and occurred_at between timestamptz '<T1>' and timestamptz '<T2>' order by occurred_at",
    "actor_everything": "select occurred_at, action, referral_id, patient_id, old_provider_id, new_provider_id, request_id from record_access where actor = '<email>' and occurred_at between timestamptz '<T1>' and timestamptz '<T2>' order by occurred_at desc limit 500",
    "actor_scope": "select count(distinct patient_id), count(distinct referral_id), count(*), min(occurred_at), max(occurred_at) from record_access where actor = '<email>' and occurred_at between timestamptz '<T1>' and timestamptz '<T2>'",
    "assignment_history": "select occurred_at, actor, old_provider_id, new_provider_id, request_id from record_access where referral_id = <referral-id> and action = 'referral.assign' and occurred_at between timestamptz '<T1>' and timestamptz '<T2>' order by occurred_at",
    "prune": "delete from record_access where occurred_at < now() - interval '<N> days'",
}

T1 = "2026-01-01 00:00:00+00"
T2 = "2026-01-31 00:00:00+00"
A = "a@example.test"
B = "b@example.test"


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=UTC)


def _fill(name: str, **extra: str) -> str:
    values = {
        "<T1>": T1,
        "<T2>": T2,
        "<patient-id>": "1",
        "<referral-id>": "1",
        "<email>": A,
        **{f"<{k}>": v for k, v in extra.items()},
    }
    sql = RUNBOOK_SQL[name]
    for key, value in values.items():
        sql = sql.replace(key, value)
    return sql


def _run(sql: str, eng=engine) -> list[tuple]:
    with eng.connect() as conn:
        return [tuple(r) for r in conn.execute(text(sql))]


@pytest.fixture()
def rows(db):
    def row(occurred_at, actor, action, referral_id, patient_id, old=None, new=None):
        return RecordAccess(
            occurred_at=occurred_at,
            actor=actor,
            action=action,
            referral_id=referral_id,
            patient_id=patient_id,
            old_provider_id=old,
            new_provider_id=new,
            request_id="req-x",
        )

    db.add_all(
        [
            row(_at(5), A, "referral.read", 1, 1),
            row(_at(6), A, "referral.list", 1, 1),
            row(_at(7), A, "referral.assign", 1, 1, None, 7),
            row(_at(8), A, "referral.assign", 1, 1, 7, 8),
            # Out of window, same patient/referral/actor.
            row(datetime(2025, 12, 1, tzinfo=UTC), A, "referral.read", 1, 1),
            # Another actor on another patient/referral.
            row(_at(9), B, "referral.read", 2, 2),
        ]
    )
    db.commit()


def test_templates_are_sql_helper_safe():
    for name, sql in RUNBOOK_SQL.items():
        assert '"' not in sql, name
        assert "::" not in sql, name
        assert not re.search(r"(?<![\w:]):\w", sql), name


def test_runbook_queries_return_expected_rows(rows):
    patient = _run(_fill("patient_window"))
    assert len(patient) == 4
    assert {r[1] for r in patient} == {A}

    referral = _run(_fill("referral_window"))
    assert len(referral) == 4
    assert [r[2] for r in referral] == [
        "referral.read",
        "referral.list",
        "referral.assign",
        "referral.assign",
    ]

    everything = _run(_fill("actor_everything"))
    assert len(everything) == 4
    assert everything[0][0] == _at(8)  # newest first
    assert all(r[3] == 1 for r in everything)

    scope = _run(_fill("actor_scope"))[0]
    assert scope[:3] == (1, 1, 4)
    assert scope[3] == _at(5) and scope[4] == _at(8)

    history = _run(_fill("assignment_history"))
    assert [(r[2], r[3]) for r in history] == [(None, 7), (7, 8)]


def test_prune_is_owner_only(db):
    now = datetime.now(UTC)
    db.add_all(
        [
            RecordAccess(
                occurred_at=now - timedelta(days=60),
                actor=A,
                action="referral.read",
                referral_id=1,
                patient_id=1,
            ),
            RecordAccess(
                occurred_at=now,
                actor=A,
                action="referral.read",
                referral_id=2,
                patient_id=2,
            ),
        ]
    )
    db.commit()
    sql = _fill("prune", N="30")

    with pytest.raises(
        ProgrammingError, match=r"InsufficientPrivilege|permission denied"
    ):
        with engine.begin() as conn:
            conn.execute(text(sql))

    with owner_engine.begin() as conn:
        result = conn.execute(text(sql))
        assert result.rowcount == 1
    assert _run("select referral_id from record_access", owner_engine) == [(2,)]
