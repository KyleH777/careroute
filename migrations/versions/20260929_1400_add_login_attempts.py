"""add login_attempts

Revision ID: 5c1f0e7a9b21
Revises: a6ca29d19c0c
Create Date: 2026-09-29 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '5c1f0e7a9b21'
down_revision: str | None = 'a6ca29d19c0c'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('login_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('client_ip', postgresql.INET(), nullable=True),
    sa.Column('outcome', sa.Enum('success', 'failure', 'rate_limited', name='login_outcome'), nullable=False),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_login_attempts_email_time', 'login_attempts', ['email', 'occurred_at'], unique=False)
    op.create_index('ix_login_attempts_ip_time', 'login_attempts', ['client_ip', 'occurred_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_login_attempts_ip_time', table_name='login_attempts')
    op.drop_index('ix_login_attempts_email_time', table_name='login_attempts')
    op.drop_table('login_attempts')
    # Autogenerate never emits DROP TYPE for native enums; without this a
    # downgrade -> upgrade round-trip fails with DuplicateObject.
    op.execute('DROP TYPE IF EXISTS login_outcome')
