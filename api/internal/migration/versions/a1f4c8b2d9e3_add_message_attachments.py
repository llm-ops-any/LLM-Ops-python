"""add message attachments

Revision ID: a1f4c8b2d9e3
Revises: 36c79303c825
Create Date: 2026-10-26 10:00:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1f4c8b2d9e3'
down_revision = '36c79303c825'
branch_labels = None
depends_on = None


def upgrade():
    # 为消息表新增附件元信息字段，用于持久化随消息上传的附件(历史消息展示与追查)
    with op.batch_alter_table('message', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'attachments',
                postgresql.JSONB(astext_type=sa.Text()),
                server_default=sa.text("'[]'::jsonb"),
                nullable=False,
            )
        )


def downgrade():
    with op.batch_alter_table('message', schema=None) as batch_op:
        batch_op.drop_column('attachments')
