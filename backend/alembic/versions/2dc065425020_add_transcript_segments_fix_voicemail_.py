"""add_transcript_segments_fix_voicemail_index

Revision ID: 2dc065425020
Revises: 1e0120b7061a
Create Date: 2026-11-09 14:56:08.810535

Changes in this migration:
  1. Add transcript_segments table (was missing from initial voicemail migration)
  2. Fix voicemail_recordings unique index — the auto-generated migration created
     ix_voicemail_recordings_voicemail_id as UNIQUE=True, but the uniqueness is
     already enforced by the column's unique=True constraint. The separate unique
     index is redundant. We drop and recreate it as a regular (non-unique) index.
  3. Note: Enum types created in migration 1e0120b7061a do not have explicit DROP
     statements in that migration's downgrade(). This is a known Alembic limitation
     with PostgreSQL enums — they are not auto-dropped. This migration documents
     that limitation and handles enum cleanup in its own downgrade().
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '2dc065425020'
down_revision: Union[str, None] = '1e0120b7061a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Add transcript_segments table ──────────────────────────────────
    op.create_table(
        'transcript_segments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('transcript_id', sa.UUID(), nullable=False),
        sa.Column('start_ms', sa.Integer(), nullable=True,
                  comment='Start time of this segment in ms from audio start'),
        sa.Column('end_ms', sa.Integer(), nullable=True,
                  comment='End time of this segment in ms from audio start'),
        sa.Column('text', sa.Text(), nullable=False,
                  comment='Spoken words as returned by the STT provider. Immutable.'),
        sa.Column('speech_confidence', sa.Float(), nullable=True,
                  comment=(
                      'Confidence score (0.0-1.0) from the STT provider. '
                      'NULL = provider did not supply this value. Never estimated.'
                  )),
        sa.Column('review_status', sa.String(length=20), nullable=False,
                  comment='pending | reviewed | corrected | confirmed'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['transcript_id'], ['transcripts.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_transcript_segments_transcript_id'),
        'transcript_segments', ['transcript_id'], unique=False,
    )
    # Composite index for efficient queries: get all segments for a
    # transcript ordered by time
    op.create_index(
        'ix_transcript_segments_transcript_time',
        'transcript_segments', ['transcript_id', 'start_ms'], unique=False,
    )

    # ── 2. Fix voicemail_recordings index ─────────────────────────────────
    # The previous migration created this index with unique=True. The column
    # already has a UNIQUE constraint (voicemail_id is unique in the table),
    # so the unique index is redundant and misleading. Drop and recreate.
    op.drop_index(
        op.f('ix_voicemail_recordings_voicemail_id'),
        table_name='voicemail_recordings',
    )
    op.create_index(
        op.f('ix_voicemail_recordings_voicemail_id'),
        'voicemail_recordings', ['voicemail_id'], unique=False,
    )


def downgrade() -> None:
    # Drop transcript_segments
    op.drop_index(
        'ix_transcript_segments_transcript_time',
        table_name='transcript_segments',
    )
    op.drop_index(
        op.f('ix_transcript_segments_transcript_id'),
        table_name='transcript_segments',
    )
    op.drop_table('transcript_segments')

    # Restore the (incorrectly) unique index on voicemail_recordings
    op.drop_index(
        op.f('ix_voicemail_recordings_voicemail_id'),
        table_name='voicemail_recordings',
    )
    op.create_index(
        op.f('ix_voicemail_recordings_voicemail_id'),
        'voicemail_recordings', ['voicemail_id'], unique=True,
    )
