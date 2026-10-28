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
from wtforms.validators import DataRequired, Optional, UUID

from internal.lib.helper import datetime_to_timestamp
from internal.model import App, Conversation
from .chat_attachment_schema import ChatAttachmentsMixin
from .schema import ListField


class GetWebAppResp(Schema):
    """获取WebApp基础信息响应结构"""
    id = fields.UUID(dump_default="")
    icon = fields.String(dump_default="")
    name = fields.String(dump_default="")
    description = fields.String(dump_default="")
    app_config = fields.Dict(dump_default={})
    # CR-16102810：WebApp 页要按这个开关决定是否显示朗读按钮
    text_to_speech = fields.Dict(dump_default={})

    @pre_dump
    def process_data(self, data: App, **kwargs):
        app_config = data.app_config
        # 说明：text_to_speech 是 JSONB，历史数据可能没有该键，统一兜成关闭
        tts = app_config.text_to_speech or {}
        return {
            "id": data.id,
            "icon": data.icon,
            "name": data.name,
            "description": data.description,
            "app_config": {
                "opening_statement": app_config.opening_statement,
                "opening_questions": app_config.opening_questions,
                "suggested_after_answer": app_config.suggested_after_answer,
            },
            "text_to_speech": {
                "enable": bool(tts.get("enable", False)),
                "voice": tts.get("voice", ""),
                "auto_play": bool(tts.get("auto_play", False)),
            },
        }


class WebAppChatReq(ChatAttachmentsMixin, FlaskForm):
    """WebApp对话请求结构体"""
    conversation_id = StringField("conversation_id", default="", validators=[
        Optional(),
        UUID(message="会话id格式必须为uuid")
    ])
    query = StringField("query", default="", validators=[
        DataRequired(message="用户提问query不能为空")
    ])
    files = ListField("files", default=[])


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
