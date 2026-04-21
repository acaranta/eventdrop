"""add phase to archive_requests

Revision ID: e5g7i9c3d1f4
Revises: d4f6h8a2c0e3
Create Date: 2026-04-21

"""
from alembic import op
import sqlalchemy as sa

revision = 'e5g7i9c3d1f4'
down_revision = 'd4f6h8a2c0e3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col['name'] for col in inspector.get_columns('archive_requests')}

    if 'phase' not in existing_cols:
        op.add_column('archive_requests',
            sa.Column('phase', sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column('archive_requests', 'phase')
