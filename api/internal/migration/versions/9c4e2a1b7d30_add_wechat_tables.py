"""add wechat tables

Revision ID: 9c4e2a1b7d30
Revises: b7d21e9c4a55
Create Date: 2026-10-28 19:20:00.000000

CR-16102807：微信公众号发布接入，新增 3 张表。
说明：结构照课程原项目 b017b44df199，但不含原项目 493395dc50b8 的 message.image_urls
     （本项目用 attachments，见 CR-16102701）。
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '9c4e2a1b7d30'
down_revision = 'b7d21e9c4a55'
branch_labels = None
depends_on = None


def upgrade():
    # 1.应用与公众号的配置（一对一 app）
    op.create_table('wechat_config',
                    sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
                    sa.Column('app_id', sa.UUID(), nullable=False),
                    sa.Column('wechat_app_id', sa.String(length=255),
                              server_default=sa.text("''::character varying"), nullable=True),
                    sa.Column('wechat_app_secret', sa.String(length=255),
                              server_default=sa.text("''::character varying"), nullable=True),
                    sa.Column('wechat_token', sa.String(length=255),
                              server_default=sa.text("''::character varying"), nullable=True),
                    sa.Column('status', sa.String(length=255),
                              server_default=sa.text("''::character varying"), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'),
                              nullable=False),
                    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'),
                              nullable=False),
                    sa.PrimaryKeyConstraint('id', name='pk_wechat_config_id')
                    )
    with op.batch_alter_table('wechat_config', schema=None) as batch_op:
        batch_op.create_index('wechat_config_app_id_idx', ['app_id'], unique=False)

    # 2.openid 与终端用户的关联（同一公众号下 openid 唯一）
    op.create_table('wechat_end_user',
                    sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
                    sa.Column('openid', sa.String(), nullable=False),
                    sa.Column('app_id', sa.UUID(), nullable=False),
                    sa.Column('end_user_id', sa.UUID(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'),
                              nullable=False),
                    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'),
                              nullable=False),
                    sa.PrimaryKeyConstraint('id', name='pk_wechat_end_user_id')
                    )
    with op.batch_alter_table('wechat_end_user', schema=None) as batch_op:
        batch_op.create_index('wechat_end_user_openid_app_id_idx', ['openid', 'app_id'], unique=False)

    # 3.待推送队列（Agent 异步跑完后等用户回复「1」取结果）
    op.create_table('wechat_message',
                    sa.Column('id', sa.UUID(), server_default=sa.text('uuid_generate_v4()'), nullable=False),
                    sa.Column('wechat_end_user_id', sa.UUID(), nullable=False),
                    sa.Column('message_id', sa.UUID(), nullable=False),
                    sa.Column('is_pushed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'),
                              nullable=False),
                    sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP(0)'),
                              nullable=False),
                    sa.PrimaryKeyConstraint('id', name='pk_wechat_message_id')
                    )
    with op.batch_alter_table('wechat_message', schema=None) as batch_op:
        batch_op.create_index('wechat_message_wechat_end_user_id_idx', ['wechat_end_user_id'], unique=False)


def downgrade():
    # 倒序删除，索引先于表
    with op.batch_alter_table('wechat_message', schema=None) as batch_op:
        batch_op.drop_index('wechat_message_wechat_end_user_id_idx')
    op.drop_table('wechat_message')

    with op.batch_alter_table('wechat_end_user', schema=None) as batch_op:
        batch_op.drop_index('wechat_end_user_openid_app_id_idx')
    op.drop_table('wechat_end_user')

    with op.batch_alter_table('wechat_config', schema=None) as batch_op:
        batch_op.drop_index('wechat_config_app_id_idx')
    op.drop_table('wechat_config')
