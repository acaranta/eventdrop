"""add archive status and async fields

Revision ID: c2d4f6a8b0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-04-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'c2d4f6a8b0e1'
down_revision = 'a1c3e5f7b9d2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_cols = {col['name'] for col in inspector.get_columns('archive_requests')}

    if 'status' not in existing_cols:
        op.add_column('archive_requests',
            sa.Column('status', sa.String(20), nullable=False, server_default='ready'))
    if 'error_message' not in existing_cols:
        op.add_column('archive_requests',
            sa.Column('error_message', sa.String(1024), nullable=True))
    # Make file_path nullable for pending archives
    op.alter_column('archive_requests', 'file_path', nullable=True)


def downgrade() -> None:
    op.drop_column('archive_requests', 'status')
    op.drop_column('archive_requests', 'error_message')
    op.alter_column('archive_requests', 'file_path', nullable=False)
