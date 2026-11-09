"""fix_timezone_columns

Revision ID: c1044e22c216
Revises: 39effeb95c75
Create Date: 2026-11-05 11:36:20.372164

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1044e22c216'
down_revision: Union[str, None] = '39effeb95c75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Fix 1: expires_at VARCHAR -> TIMESTAMPTZ (simple cast, same data type family)
    op.alter_column(
        'user_sessions', 'expires_at',
        existing_type=postgresql.TIMESTAMP(),
        type_=sa.DateTime(timezone=True),
        existing_comment='When this refresh token expires.',
        existing_nullable=False,
    )
    # Fix 2: user_decided_at VARCHAR -> TIMESTAMPTZ
    # PostgreSQL cannot auto-cast VARCHAR to TIMESTAMPTZ.
    # The column is currently empty in all rows (feature not yet used),
    # so we drop and recreate it cleanly instead of casting garbage string data.
    op.drop_column('verification_results', 'user_decided_at')
    op.add_column(
        'verification_results',
        sa.Column(
            'user_decided_at',
            sa.DateTime(timezone=True),
            nullable=True,
            comment='Timestamp when the user made their decision',
        ),
    )


def downgrade() -> None:
    op.drop_column('verification_results', 'user_decided_at')
    op.add_column(
        'verification_results',
        sa.Column(
            'user_decided_at',
            sa.VARCHAR(),
            nullable=True,
            comment='Timestamp when the user made their decision',
        ),
    )
    op.alter_column(
        'user_sessions', 'expires_at',
        existing_type=sa.DateTime(timezone=True),
        type_=postgresql.TIMESTAMP(),
        existing_comment='When this refresh token expires.',
        existing_nullable=False,
    )
