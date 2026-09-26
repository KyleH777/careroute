"""Database privilege contract (ADR-0010).

The app connects as a DML-only role; only the migrate role can change the
schema. These tests run as the app's own connection, so a migration that
creates a table the app can't use, or anything that hands the app DDL rights,
fails CI before it reaches Azure.
"""

import os

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db import Base, engine

APP_ROLE = os.environ.get("APP_DB_ROLE", "careroute_app")
MIGRATE_ROLE = os.environ.get("MIGRATE_DB_ROLE", "careroute_migrate")


def _scalar(sql: str, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar_one()


def test_connected_as_app_role():
    assert _scalar("select current_user") == APP_ROLE


@pytest.mark.parametrize("table", [t.name for t in Base.metadata.sorted_tables])
@pytest.mark.parametrize("privilege", ["SELECT", "INSERT", "UPDATE", "DELETE"])
def test_app_has_dml_on_every_model_table(table, privilege):
    assert _scalar(
        "select has_table_privilege(current_user, :t, :p)", t=table, p=privilege
    )


@pytest.mark.parametrize(
    "statement",
    [
        "CREATE TABLE _evil (id int)",
        "ALTER TABLE facilities ADD COLUMN _evil int",
        "DROP TABLE users",
        "TRUNCATE users",
    ],
)
def test_app_cannot_change_schema_or_truncate(statement):
    with engine.connect() as conn:
        with pytest.raises(ProgrammingError) as exc:
            conn.execute(text(statement))
        conn.rollback()
    assert isinstance(exc.value.orig, psycopg.errors.InsufficientPrivilege)


@pytest.mark.parametrize("privilege", ["INSERT", "UPDATE", "DELETE"])
def test_app_cannot_write_alembic_version(privilege):
    assert not _scalar(
        "select has_table_privilege(current_user, 'alembic_version', :p)",
        p=privilege,
    )


def test_app_role_is_not_privileged():
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "select rolsuper, rolcreaterole, rolcreatedb "
                "from pg_roles where rolname = current_user"
            )
        ).one()
        can_create = conn.execute(
            text("select has_schema_privilege('public', 'CREATE')")
        ).scalar_one()
    assert tuple(row) == (False, False, False)
    assert can_create is False


def test_every_public_object_is_owned_by_migrate_role():
    with engine.connect() as conn:
        misowned = conn.execute(
            text(
                """
                select c.relname, pg_get_userbyid(c.relowner)
                from pg_class c
                where c.relnamespace = 'public'::regnamespace
                  and c.relkind in ('r', 'p', 'v', 'm', 'S')
                  and pg_get_userbyid(c.relowner) <> :owner
                union all
                select t.typname, pg_get_userbyid(t.typowner)
                from pg_type t
                where t.typnamespace = 'public'::regnamespace
                  and t.typtype in ('e', 'd')
                  and pg_get_userbyid(t.typowner) <> :owner
                """
            ),
            {"owner": MIGRATE_ROLE},
        ).all()
    assert misowned == []
