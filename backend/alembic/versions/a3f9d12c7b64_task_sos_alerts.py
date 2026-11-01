"""task sos alerts

Revision ID: a3f9d12c7b64
Revises: c22bd374fcad
Create Date: 2026-10-14 21:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f9d12c7b64'
down_revision: Union[str, None] = 'c22bd374fcad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'task_sos_alerts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('task_id', sa.String(length=36), nullable=False),
        sa.Column('raised_by_id', sa.String(length=36), nullable=False),
        sa.Column('raised_by_role', sa.String(length=20), nullable=False),
        sa.Column('previous_status', sa.String(length=30), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('location_history', sa.JSON(), nullable=False),
        sa.Column('resolved_by_id', sa.String(length=36), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['raised_by_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['resolved_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_task_sos_alerts_status'), 'task_sos_alerts', ['status'], unique=False)
    op.create_index(op.f('ix_task_sos_alerts_task_id'), 'task_sos_alerts', ['task_id'], unique=False)
    op.create_index(op.f('ix_task_sos_alerts_raised_by_id'), 'task_sos_alerts', ['raised_by_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_sos_alerts_raised_by_id'), table_name='task_sos_alerts')
    op.drop_index(op.f('ix_task_sos_alerts_task_id'), table_name='task_sos_alerts')
    op.drop_index(op.f('ix_task_sos_alerts_status'), table_name='task_sos_alerts')
    op.drop_table('task_sos_alerts')
