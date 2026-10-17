#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : chat.py
@Desc    : uino 统一中转平台聊天模型

说明：接口地址(base_url)与密钥(api_key)均通过环境变量注入，
      即 OPENAI_API_BASE 与 OPENAI_API_KEY，不在代码/配置中硬编码凭证。
      底层 ChatOpenAI 会自动从这两个环境变量读取。
"""
from langchain_openai import ChatOpenAI

from internal.core.language_model.entities.model_entity import BaseLanguageModel


class Chat(ChatOpenAI, BaseLanguageModel):
    """uino 统一中转平台聊天模型（OpenAI 兼容协议）"""

    def get_num_tokens_from_messages(self, messages) -> int:
        """复用BaseLanguageModel的通用实现，兼容tiktoken不认识的第三方模型名"""
        return BaseLanguageModel.get_num_tokens_from_messages(self, messages)
