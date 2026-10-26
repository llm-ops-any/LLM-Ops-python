#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/12/10 22:09
@Author  : thezehui@gmail.com
@File    : web_app_schema.py
"""
from flask_wtf import FlaskForm
from marshmallow import Schema, fields, pre_dump
from wtforms import StringField, BooleanField
from wtforms.validators import DataRequired, Optional, UUID, ValidationError

from internal.entity.upload_file_entity import MAX_CHAT_ATTACHMENT_COUNT
from internal.lib.helper import datetime_to_timestamp
from internal.model import App, Conversation
from .schema import ListField


class GetWebAppResp(Schema):
    """获取WebApp基础信息响应结构"""
    id = fields.UUID(dump_default="")
    icon = fields.String(dump_default="")
    name = fields.String(dump_default="")
    description = fields.String(dump_default="")
    app_config = fields.Dict(dump_default={})

    @pre_dump
    def process_data(self, data: App, **kwargs):
        app_config = data.app_config
        return {
            "id": data.id,
            "icon": data.icon,
            "name": data.name,
            "description": data.description,
            "app_config": {
                "opening_statement": app_config.opening_statement,
                "opening_questions": app_config.opening_questions,
                "suggested_after_answer": app_config.suggested_after_answer,
            }
        }


class WebAppChatReq(FlaskForm):
    """WebApp对话请求结构体"""
    conversation_id = StringField("conversation_id", default="", validators=[
        Optional(),
        UUID(message="会话id格式必须为uuid")
    ])
    query = StringField("query", default="", validators=[
        DataRequired(message="用户提问query不能为空")
    ])
    files = ListField("files", default=[])

    def validate_files(self, field: ListField) -> None:
        """校验随消息上传的附件列表，附件由前端上传解析后携带(name+text)"""
        # 1.未传递附件时重置为空列表
        if field.data is None:
            field.data = []
            return

        # 2.校验数据类型与数量
        if not isinstance(field.data, list):
            raise ValidationError("附件列表格式错误")
        if len(field.data) > MAX_CHAT_ATTACHMENT_COUNT:
            raise ValidationError(f"单次提问最多携带{MAX_CHAT_ATTACHMENT_COUNT}个附件")

        # 3.校验每个附件的数据结构
        for attachment in field.data:
            if not isinstance(attachment, dict):
                raise ValidationError("附件数据格式错误")
            if not str(attachment.get("name") or "").strip():
                raise ValidationError("附件名称不能为空")
            text = str(attachment.get("text") or "").strip()
            url = str(attachment.get("url") or "").strip()
            if not text and not url:
                raise ValidationError("附件内容不能为空")
            if len(text) > 100000:
                raise ValidationError("单个附件内容过长，请重新上传")


class GetConversationsReq(FlaskForm):
    """获取WebApp会话列表请求结构体"""
    is_pinned = BooleanField("is_pinned", default=False)


class GetConversationsResp(Schema):
    """获取WebApp会话列表响应结构体"""
    id = fields.UUID(dump_default="")
    name = fields.String(dump_default="")
    summary = fields.String(dump_default="")
    created_at = fields.Integer(dump_default=0)

    @pre_dump
    def process_data(self, data: Conversation, **kwargs):
        return {
            "id": data.id,
            "name": data.name,
            "summary": data.summary,
            "created_at": datetime_to_timestamp(data.created_at),
        }
