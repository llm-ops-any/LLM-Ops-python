#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/11/19 22:16
@Author  : thezehui@gmail.com
@File    : openapi_schema.py
"""
import uuid

from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import DataRequired, UUID, Optional, ValidationError

from .chat_attachment_schema import ChatAttachmentsMixin
from .schema import ListField


class OpenAPIChatReq(ChatAttachmentsMixin, FlaskForm):
    """开放API聊天接口请求结构体"""
    app_id = StringField("app_id", validators=[
        DataRequired("应用id不能为空"),
        UUID("应用id格式必须为UUID"),
    ])
    end_user_id = StringField("end_user_id", default="", validators=[
        Optional(),
        UUID("终端用户id必须为UUID"),
    ])
    conversation_id = StringField("conversation_id", default="")
    query = StringField("query", default="", validators=[
        DataRequired("用户提问query不能为空"),
    ])
    stream = BooleanField("stream", default=True)
    # 随提问上传的附件(前端上传解析后回传)，校验规则与调试对话/WebApp/辅助Agent统一走Mixin
    files = ListField("files", default=[])

    def validate_conversation_id(self, field: StringField) -> None:
        """自定义校验conversation_id函数"""
        # 1.检测是否传递数据，如果传递了，则类型必须为UUID
        if field.data:
            try:
                uuid.UUID(field.data)
            except Exception as _:
                raise ValidationError("会话id格式必须为UUID")

            # 2.终端用户id是不是为空
            if not self.end_user_id.data:
                raise ValidationError("传递会话id则终端用户id不能为空")
