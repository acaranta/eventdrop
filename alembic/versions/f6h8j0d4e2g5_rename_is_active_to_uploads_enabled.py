"""rename events.is_active to uploads_enabled

The flag only ever gated new uploads — it never affected gallery
visibility, which is governed by is_gallery_public. Renaming it to
match what it does.

Revision ID: f6h8j0d4e2g5
Revises: e5g7i9c3d1f4
Create Date: 2026-07-19

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6h8j0d4e2g5'
down_revision = 'e5g7i9c3d1f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_cols = {col['name'] for col in sa.inspect(bind).get_columns('events')}

    if 'is_active' in existing_cols and 'uploads_enabled' not in existing_cols:
        # batch_alter_table: SQLite cannot rename columns in place on older versions
        with op.batch_alter_table('events') as batch_op:
            batch_op.alter_column(
                'is_active',
                new_column_name='uploads_enabled',
                existing_type=sa.Boolean(),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    existing_cols = {col['name'] for col in sa.inspect(bind).get_columns('events')}

    if 'uploads_enabled' in existing_cols and 'is_active' not in existing_cols:
        with op.batch_alter_table('events') as batch_op:
            batch_op.alter_column(
                'uploads_enabled',
                new_column_name='is_active',
                existing_type=sa.Boolean(),
                existing_nullable=False,
            )
