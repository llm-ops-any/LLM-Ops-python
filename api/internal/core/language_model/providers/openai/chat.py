#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/12/01 11:48
@Author  : thezehui@gmail.com
@File    : chat.py
"""
from langchain_openai import ChatOpenAI

from internal.core.language_model.entities.model_entity import BaseLanguageModel


class Chat(ChatOpenAI, BaseLanguageModel):
    """OpenAI聊天模型基类"""

    def get_num_tokens_from_messages(self, messages) -> int:
        """复用BaseLanguageModel的通用实现，兼容tiktoken不认识的第三方模型名"""
        return BaseLanguageModel.get_num_tokens_from_messages(self, messages)
