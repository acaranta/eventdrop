"""add batch fields to archive_requests

Revision ID: d4f6h8a2c0e3
Revises: c2d4f6a8b0e1
Create Date: 2026-04-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'd4f6h8a2c0e3'
down_revision = 'c2d4f6a8b0e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col['name'] for col in inspector.get_columns('archive_requests')}

    if 'batch_id' not in existing_cols:
        op.add_column('archive_requests',
            sa.Column('batch_id', sa.String(36), nullable=True))
        op.create_index('ix_archive_requests_batch_id', 'archive_requests', ['batch_id'])
    if 'part_index' not in existing_cols:
        op.add_column('archive_requests',
            sa.Column('part_index', sa.Integer, nullable=False, server_default='0'))
    if 'total_parts' not in existing_cols:
        op.add_column('archive_requests',
            sa.Column('total_parts', sa.Integer, nullable=False, server_default='1'))


def downgrade() -> None:
    op.drop_index('ix_archive_requests_batch_id', 'archive_requests')
    op.drop_column('archive_requests', 'batch_id')
    op.drop_column('archive_requests', 'part_index')
    op.drop_column('archive_requests', 'total_parts')
