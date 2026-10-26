#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : platform_setting.py
@Desc    : 平台级设置表模型，采用KV结构存储，新增设置项时无需再变更表结构
"""
import uuid

from sqlalchemy import Column, DateTime, Index, PrimaryKeyConstraint, String, Text, text

from internal.extension.database_extension import db


class PlatformSetting(db.Model):
    """平台设置表模型"""
    __tablename__ = "platform_setting"
    __table_args__ = (
        PrimaryKeyConstraint("id", name="pk_platform_setting_id"),
        Index("platform_setting_name_idx", "name", unique=True),
    )

    id = Column(
        "id",
        db.UUID,
        nullable=False,
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("uuid_generate_v4()"),
    )
    name = Column("name", String(255), nullable=False, server_default=text("''::character varying"))
    value = Column("value", Text, nullable=False, server_default=text("''::text"))
    updated_at = Column(
        "updated_at",
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP(0)"),
        onupdate=text("CURRENT_TIMESTAMP(0)"),
    )
    created_at = Column("created_at", DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP(0)"))
