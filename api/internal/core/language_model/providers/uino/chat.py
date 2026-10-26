#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : chat.py
@Desc    : uino 统一中转平台聊天模型

说明：
1. 接口地址(base_url)与密钥(api_key)优先取"设置-大模型设置"里保存的配置，
   未配置时回退环境变量 OPENAI_API_BASE 与 OPENAI_API_KEY；
2. 凭证在构造函数内统一补齐，因此项目里所有直接实例化 Chat(...) 的位置
   （会话命名/摘要/建议问题、提示词优化、应用预设生成、辅助Agent）都会自动跟随页面配置；
3. 调用方显式传入 openai_api_base / openai_api_key 时以显式传参为准。
"""
from langchain_openai import ChatOpenAI

from internal.core.language_model.entities.model_entity import BaseLanguageModel


class Chat(ChatOpenAI, BaseLanguageModel):
    """uino 统一中转平台聊天模型（OpenAI 兼容协议）"""

    def __init__(self, **kwargs):
        """构造时补齐接口地址与密钥，避免各处调用点各自读取配置"""
        # 说明：延迟导入，避免 providers 与 service 包之间的循环导入
        from internal.service.model_provider_service import get_active_config

        config = get_active_config()
        if config.base_url and not kwargs.get("openai_api_base") and not kwargs.get("base_url"):
            kwargs["openai_api_base"] = config.base_url
        if config.api_key and not kwargs.get("openai_api_key") and not kwargs.get("api_key"):
            kwargs["openai_api_key"] = config.api_key

        super().__init__(**kwargs)

    def get_num_tokens_from_messages(self, messages) -> int:
        """复用BaseLanguageModel的通用实现，兼容tiktoken不认识的第三方模型名"""
        return BaseLanguageModel.get_num_tokens_from_messages(self, messages)
