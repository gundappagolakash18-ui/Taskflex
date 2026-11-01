"""email OTP verification

Revision ID: a3f7c21d94be
Revises: eb014425e109
Create Date: 2026-10-05 12:10:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f7c21d94be'
down_revision: Union[str, None] = 'eb014425e109'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('email_otps',
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consumed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_email_otps_created_at'), 'email_otps', ['created_at'], unique=False)
    op.create_index(op.f('ix_email_otps_email'), 'email_otps', ['email'], unique=False)
    op.create_index(op.f('ix_email_otps_updated_at'), 'email_otps', ['updated_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_email_otps_updated_at'), table_name='email_otps')
    op.drop_index(op.f('ix_email_otps_email'), table_name='email_otps')
    op.drop_index(op.f('ix_email_otps_created_at'), table_name='email_otps')
    op.drop_table('email_otps')
