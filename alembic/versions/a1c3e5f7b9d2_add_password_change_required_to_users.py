"""add password_change_required to users

Revision ID: a1c3e5f7b9d2
Revises: b1546baf39b1
Create Date: 2026-04-17

"""
from alembic import op
import sqlalchemy as sa

revision = 'a1c3e5f7b9d2'
down_revision = 'b1546baf39b1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'users',
        sa.Column('password_change_required', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column('users', 'password_change_required')
