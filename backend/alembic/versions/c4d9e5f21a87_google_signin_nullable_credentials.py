"""google sign-in nullable credentials

Revision ID: c4d9e5f21a87
Revises: a3f7c21d94be
Create Date: 2026-10-04 09:30:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4d9e5f21a87'
down_revision: Union[str, None] = 'a3f7c21d94be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Google-only accounts have no password and no phone number yet.
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('phone', existing_type=sa.String(length=20), nullable=True)
        batch_op.alter_column('password_hash', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table('users') as batch_op:
        batch_op.alter_column('password_hash', existing_type=sa.String(length=255), nullable=False)
        batch_op.alter_column('phone', existing_type=sa.String(length=20), nullable=False)
