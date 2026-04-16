"""add gps columns to media files

Revision ID: b1546baf39b1
Revises:
Create Date: 2026-04-16

"""
from alembic import op
import sqlalchemy as sa

revision = 'b1546baf39b1'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('media_files', sa.Column('gps_lat', sa.Float(), nullable=True))
    op.add_column('media_files', sa.Column('gps_lon', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('media_files', 'gps_lon')
    op.drop_column('media_files', 'gps_lat')
