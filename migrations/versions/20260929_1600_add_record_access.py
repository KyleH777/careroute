"""add record_access

Revision ID: 8d2b6f4a1c37
Revises: 5c1f0e7a9b21
Create Date: 2026-09-29 16:00:00.000000
"""

import os
import re
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = '8d2b6f4a1c37'
down_revision: str | None = '5c1f0e7a9b21'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIONS = (
    "'referral.list', 'referral.read', 'patient.create', "
    "'referral.create', 'referral.assign', 'referral.status'"
)


def upgrade() -> None:
    op.create_table('record_access',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('actor', sa.String(length=254), nullable=False),
        sa.Column('action', sa.String(length=32), nullable=False),
        sa.Column('referral_id', sa.Integer(), nullable=True),
        sa.Column('patient_id', sa.Integer(), nullable=True),
        sa.Column('old_provider_id', sa.Integer(), nullable=True),
        sa.Column('new_provider_id', sa.Integer(), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.CheckConstraint(f"action IN ({_ACTIONS})", name='ck_record_access_action'),
        sa.CheckConstraint('referral_id IS NOT NULL OR patient_id IS NOT NULL', name='ck_record_access_target'),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_record_access_patient_time', 'record_access', ['patient_id', 'occurred_at'], unique=False)
    op.create_index('ix_record_access_referral_time', 'record_access', ['referral_id', 'occurred_at'], unique=False)
    op.create_index('ix_record_access_actor_time', 'record_access', ['actor', 'occurred_at'], unique=False)

    # Default privileges from scripts/db_roles.py granted the app role
    # SELECT/INSERT/UPDATE/DELETE on creation; take back what makes the table
    # append-only (ADR-0014, RESEARCH Pitfall 1).
    role = os.environ.get("APP_DB_ROLE", "careroute_app")
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise RuntimeError("APP_DB_ROLE is not a valid role name")
    exists = op.get_bind().execute(
        sa.text("select 1 from pg_roles where rolname = :r"), {"r": role}
    ).scalar()
    if exists:
        op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON record_access FROM "{role}"')


def downgrade() -> None:
    op.drop_index('ix_record_access_actor_time', table_name='record_access')
    op.drop_index('ix_record_access_referral_time', table_name='record_access')
    op.drop_index('ix_record_access_patient_time', table_name='record_access')
    op.drop_table('record_access')
