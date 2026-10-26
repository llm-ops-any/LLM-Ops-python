#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""聊天附件请求校验混入类

应用调试对话、WebApp对话、辅助Agent对话都支持"随消息上传附件"，
请求体统一使用 files 字段(前端上传解析后回传)，因此把校验逻辑收敛到 Mixin，
避免每个请求结构体重复实现同一份规则。
"""
from wtforms.validators import ValidationError

from internal.entity.upload_file_entity import MAX_CHAT_ATTACHMENT_COUNT


class ChatAttachmentsMixin:
    """为带 files 字段的 FlaskForm 提供统一的附件校验"""

    def validate_files(self, field) -> None:
        """校验随消息上传的附件列表，附件由前端上传解析后携带(name + text/url)"""
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
