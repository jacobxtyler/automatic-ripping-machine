"""audiobook cd support

Revision ID: b8b701d8c4e2
Revises: edf2272c0a9d
Create Date: 2026-06-15

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8b701d8c4e2'
down_revision = 'edf2272c0a9d'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.add_column(sa.Column('audiobook_author', sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column('audiobook_disc_number', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('audiobook_total_discs', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('open_library_work_key', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('open_library_cover_id', sa.String(length=32), nullable=True))

    with op.batch_alter_table('config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('AUDIOBOOK_PATH', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('config', schema=None) as batch_op:
        batch_op.drop_column('AUDIOBOOK_PATH')

    with op.batch_alter_table('job', schema=None) as batch_op:
        batch_op.drop_column('open_library_cover_id')
        batch_op.drop_column('open_library_work_key')
        batch_op.drop_column('audiobook_total_discs')
        batch_op.drop_column('audiobook_disc_number')
        batch_op.drop_column('audiobook_author')
