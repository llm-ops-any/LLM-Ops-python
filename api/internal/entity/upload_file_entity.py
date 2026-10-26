#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/8/12 10:43
@Author  : thezehui@gmail.com
@File    : upload_file_entity.py
"""

# 允许上传的文件类型
ALLOWED_IMAGE_EXTENSION = ["jpg", "jpeg", "png", "webp", "gif", "svg"]
ALLOWED_DOCUMENT_EXTENSION = ["txt", "markdown", "md", "pdf", "html", "htm", "xlsx", "xls", "doc", "docx", "csv"]

# 对话附件（随消息上传）相关限制
# 说明：对话附件不再限制扩展名 —— 能解析出文本的走文本解析，图片与其它二进制文件走对象存储，
# 由服务端返回可访问URL（为后续多模态视觉模型预留）。
MAX_CHAT_ATTACHMENT_SIZE = 30 * 1024 * 1024  # 单个附件最大30MB
MAX_CHAT_ATTACHMENT_TEXT_LENGTH = 20000  # 单个附件解析出的文本最大字符数(超出截断)
MAX_CHAT_ATTACHMENT_COUNT = 5  # 单条消息最多携带的附件数量
MAX_CHAT_ATTACHMENT_ONE_LENGTH = 8000  # 单个附件注入上下文时的最大字符数
MAX_CHAT_ATTACHMENT_TOTAL_LENGTH = 20000  # 所有附件注入上下文时的总字符数上限
