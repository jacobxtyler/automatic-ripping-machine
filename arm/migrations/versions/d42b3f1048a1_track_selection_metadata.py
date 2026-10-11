"""Add title selection metadata to tracks

Revision ID: d42b3f1048a1
Revises: b8b701d8c4e2
Create Date: 2026-07-27

"""
from alembic import op
import sqlalchemy as sa


revision = 'd42b3f1048a1'
down_revision = 'b8b701d8c4e2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('track', schema=None) as batch_op:
        batch_op.add_column(sa.Column('playlist_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('segment_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('segment_map', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('video_resolution', sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column('video_codec', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('audio_languages', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('subtitle_languages', sa.String(length=512), nullable=True))


def downgrade():
    with op.batch_alter_table('track', schema=None) as batch_op:
        batch_op.drop_column('subtitle_languages')
        batch_op.drop_column('audio_languages')
        batch_op.drop_column('video_codec')
        batch_op.drop_column('video_resolution')
        batch_op.drop_column('segment_map')
        batch_op.drop_column('segment_count')
        batch_op.drop_column('playlist_id')
