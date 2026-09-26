"""Create and maintain CareRoute's least-privilege database roles (ADR-0010).

Run as the server admin, before migrations:

    docker compose run --rm db-roles                      # local / CI
    az containerapp job start -g careroute-rg -n careroute-db-bootstrap   # Azure

Two roles:

- careroute_migrate  owns every object in schema public and runs Alembic.
- careroute_app      SELECT/INSERT/UPDATE/DELETE only. No DDL, no TRUNCATE,
                     no access to alembic_version. The API runs as this.

Idempotent: safe on every `compose up`, after a restore, and as the password
rotation step (every run re-syncs both passwords from the environment).
Objects not owned by the migrate role, e.g. everything created before this
existed, or restored by a superuser, are handed over to it.

Environment:

    ADMIN_DATABASE_URL   admin connection (SQLAlchemy-style URL is fine)
    MIGRATE_DB_PASSWORD  password to set for the migrate role
    APP_DB_PASSWORD      password to set for the app role
    MIGRATE_DB_ROLE      default careroute_migrate
    APP_DB_ROLE          default careroute_app

Never logs a password or a connection URL.
"""

from __future__ import annotations

import logging
import os
import sys

import psycopg
from psycopg import sql

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("db_roles")

# Alembic's own DDL for its version table. Creating it here, as the migrate
# role, lets us revoke the app's default privileges on it before the first
# migration runs; Alembic reuses an existing table.
ALEMBIC_VERSION_DDL = (
    "CREATE TABLE IF NOT EXISTS alembic_version ("
    "version_num VARCHAR(32) NOT NULL, "
    "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
)

# Everything in schema public that the migrate role should own. Sequences
# owned by a table column are excluded: they follow their table.
MISOWNED_OBJECTS = """
select 'TABLE', c.relname
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relkind in ('r', 'p') and c.relowner <> %(owner)s::regrole
union all
select 'VIEW', c.relname
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relkind = 'v' and c.relowner <> %(owner)s::regrole
union all
select 'MATERIALIZED VIEW', c.relname
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relkind = 'm' and c.relowner <> %(owner)s::regrole
union all
select 'SEQUENCE', c.relname
from pg_class c
where c.relnamespace = 'public'::regnamespace
  and c.relkind = 'S' and c.relowner <> %(owner)s::regrole
  and not exists (
    select 1 from pg_depend d
    where d.objid = c.oid and d.classid = 'pg_class'::regclass
      and d.deptype in ('a', 'i')
  )
union all
select 'TYPE', t.typname
from pg_type t
where t.typnamespace = 'public'::regnamespace
  and t.typtype in ('e', 'd') and t.typowner <> %(owner)s::regrole
"""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} is not set")
    return value


def _conninfo(url: str) -> str:
    """Accept the app's SQLAlchemy URL form (postgresql+psycopg://)."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def ensure_role(cur: psycopg.Cursor, role: str, password: str) -> None:
    cur.execute("select 1 from pg_roles where rolname = %s", (role,))
    if cur.fetchone() is None:
        log.info("creating role %s", role)
        cur.execute(
            sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(role)
            )
        )
    cur.execute(
        sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {}").format(
            sql.Identifier(role), sql.Literal(password)
        )
    )


def bootstrap(conn: psycopg.Connection, migrate: str, app: str) -> int:
    """Apply the role model; returns how many objects changed owner."""
    m, a = sql.Identifier(migrate), sql.Identifier(app)
    with conn.cursor() as cur:
        ensure_role(cur, migrate, _require("MIGRATE_DB_PASSWORD"))
        ensure_role(cur, app, _require("APP_DB_PASSWORD"))

        # PG16: a non-superuser admin (Azure) may only give objects to, or act
        # as, a role it can SET ROLE to. Superusers (Compose) already can.
        cur.execute("select rolsuper from pg_roles where rolname = current_user")
        row = cur.fetchone()
        if not (row and row[0]):
            cur.execute(
                sql.SQL("GRANT {} TO CURRENT_USER WITH INHERIT FALSE, SET TRUE").format(
                    m
                )
            )

        cur.execute("select current_database()")
        db_row = cur.fetchone()
        assert db_row is not None
        db = sql.Identifier(db_row[0])
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(db, m, a))
        # The new owner needs CREATE on the schema before ownership can move.
        cur.execute(sql.SQL("GRANT CREATE, USAGE ON SCHEMA public TO {}").format(m))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(a))

        cur.execute(MISOWNED_OBJECTS, {"owner": migrate})
        misowned = cur.fetchall()
        for kind, name in misowned:
            cur.execute(
                sql.SQL("ALTER {} {} OWNER TO {}").format(
                    sql.SQL(kind), sql.Identifier(name), m
                )
            )

        # Grants and default privileges must be issued as the owner itself.
        cur.execute(sql.SQL("SET ROLE {}").format(m))
        cur.execute(ALEMBIC_VERSION_DDL)
        cur.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(a)
        )
        cur.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                "GRANT USAGE, SELECT ON SEQUENCES TO {}"
            ).format(a)
        )
        cur.execute(
            sql.SQL(
                "GRANT SELECT, INSERT, UPDATE, DELETE "
                "ON ALL TABLES IN SCHEMA public TO {}"
            ).format(a)
        )
        cur.execute(
            sql.SQL(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
            ).format(a)
        )
        cur.execute(sql.SQL("REVOKE ALL ON alembic_version FROM {}").format(a))
        cur.execute("RESET ROLE")
    return len(misowned)


def main() -> int:
    migrate = os.environ.get("MIGRATE_DB_ROLE", "careroute_migrate")
    app = os.environ.get("APP_DB_ROLE", "careroute_app")
    conninfo = _conninfo(_require("ADMIN_DATABASE_URL"))
    try:
        with psycopg.connect(conninfo) as conn:  # commits on success
            moved = bootstrap(conn, migrate, app)
    except psycopg.Error as exc:
        # The message never contains the password: it is sent as a literal
        # in ALTER ROLE, which Postgres doesn't echo back in errors.
        log.error("role bootstrap failed: %s", exc.diag.message_primary or exc)
        return 1
    log.info(
        "roles ready: %s (owner), %s (DML only); %d object(s) changed owner; "
        "passwords synced",
        migrate,
        app,
        moved,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
