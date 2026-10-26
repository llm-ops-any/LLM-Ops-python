"""add platform setting

Revision ID: b7d21e9c4a55
Revises: a1f4c8b2d9e3
Create Date: 2026-10-26 11:30:00.000000

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b7d21e9c4a55'
down_revision = 'a1f4c8b2d9e3'
branch_labels = None
depends_on = None


def upgrade():
    # 平台级设置表，采用KV结构存储大模型服务地址与API Key密文等配置
    op.create_table(
        'platform_setting',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('name', sa.String(length=255), server_default=sa.text("''::character varying"), nullable=False),
        sa.Column('value', sa.Text(), server_default=sa.text("''::text"), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='pk_platform_setting_id'),
    )
    op.create_index('platform_setting_name_idx', 'platform_setting', ['name'], unique=True)


def downgrade():
    op.drop_index('platform_setting_name_idx', table_name='platform_setting')
    op.drop_table('platform_setting')
