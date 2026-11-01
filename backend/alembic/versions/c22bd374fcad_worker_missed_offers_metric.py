"""worker missed_offers metric

Revision ID: c22bd374fcad
Revises: 7fa871c444c0
Create Date: 2026-10-13 19:43:13.817998

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c22bd374fcad'
down_revision: Union[str, None] = '7fa871c444c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('worker_profiles', sa.Column('missed_offers', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('worker_profiles', 'missed_offers')
