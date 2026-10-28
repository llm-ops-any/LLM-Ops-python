#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : audio_service.py
@Desc    : 语音能力服务（CR-16102803）

职责边界：
- 权限与归属校验（照搬课程原项目逻辑，这部分与平台无关，可直接用）；
- 按配置选 provider 并把结果转成 SSE 文本，provider 内部只管「怎么出声」。
"""
import json
import logging
from dataclasses import dataclass
from typing import Generator, Union
from uuid import UUID

from injector import inject

from internal.core.audio import BROWSER_ENGINE_MESSAGE, create_asr_provider, create_tts_provider
from internal.entity.app_entity import AppStatus
from internal.entity.conversation_entity import InvokeFrom
from internal.exception import CustomException, FailException, NotFoundException
from internal.model import Account, App, AppConfig, AppConfigVersion, Conversation, Message
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService
from .speech_provider_service import SpeechProviderService


@inject
@dataclass
class AudioService(BaseService):
    """语音服务，涵盖语音转文本、消息转语音"""
    db: SQLAlchemy
    speech_provider_service: SpeechProviderService

    # ---------------------------------------------------------------- ASR

    def audio_to_text(self, content: bytes, filename: str) -> str:
        """把音频转换成文本（仅 dashscope 档走服务端）"""
        config = self.speech_provider_service.get_active_config()
        provider = create_asr_provider(config)
        return provider.asr(content, filename)

    # ---------------------------------------------------------------- TTS

    def message_to_audio(self, message_id: UUID, account: Account) -> Union[Generator, list]:
        """把消息答案转换成流式语音事件

        返回生成器（SSE 文本流）。所有校验失败都抛业务异常，由 handler 转 code≠success。
        """
        # 1.取消息并校验归属
        message = self.get(Message, message_id)
        if not message or message.is_deleted or message.answer.strip() == "" or message.created_by != account.id:
            raise NotFoundException("该消息不存在，请核实后重试")

        # 2.校验会话状态与归属
        #    说明：本项目 Message 没有 conversation 关系属性，只能按 conversation_id 查（与原项目的差异点）
        conversation = self.get(Conversation, message.conversation_id)
        if conversation is None or conversation.is_deleted or conversation.created_by != account.id:
            raise NotFoundException("该消息会话不存在，请核实后重试")

        # 3.按调用来源取应用配置，并判断该应用是否开启文本转语音
        enable = False
        if message.invoke_from in (InvokeFrom.WEB_APP, InvokeFrom.DEBUGGER):
            app = self.get(App, conversation.app_id)
            if app is None:
                raise NotFoundException("该消息会话归属应用不存在或校验失败，请核实后重试")
            if message.invoke_from == InvokeFrom.DEBUGGER and app.account_id != account.id:
                raise NotFoundException("该消息会话归属的应用不存在或校验失败，请核实后重试")
            if message.invoke_from == InvokeFrom.WEB_APP and app.status != AppStatus.PUBLISHED:
                raise NotFoundException("该消息会话归属的应用未发布，请核实后重试")

            app_config: Union[AppConfig, AppConfigVersion] = (
                app.draft_app_config if message.invoke_from == InvokeFrom.DEBUGGER else app.app_config
            )
            text_to_speech = (app_config.text_to_speech or {}) if app_config else {}
            enable = bool(text_to_speech.get("enable", False))
        elif message.invoke_from == InvokeFrom.SERVICE_API:
            raise FailException("开放API消息不支持文本转语音服务")

        if enable is False:
            raise FailException("该应用未开启文字转语音功能，请核实后重试")

        # 4.按当前引擎合成并返回 SSE 生成器（懒加载：这里才建连接，D-07）
        config = self.speech_provider_service.get_active_config()
        provider = create_tts_provider(config)

        # 预检放在返回生成器之前：一旦响应开始流式输出，异常就无法再转成 JSON 错误，
        # 会变成「连接断了 + 后端 traceback」，前端只看到失败却不知道原因。
        if not provider.supports_tts:
            raise FailException(BROWSER_ENGINE_MESSAGE)
        if not config.has_api_key:
            raise FailException("语音服务未配置，请在「设置 → 语音服务」填写阿里百炼 API Key")

        def tts() -> Generator:
            """内部生成器：把 provider 的音频块转成 SSE 事件

            说明：流式开始后仍可能失败（超时/模型不可用），此时用 tts_error 事件告知前端，
                不再抛异常（抛了前端只会看到流被截断）。
            """
            common_data = {
                "conversation_id": str(conversation.id),
                "message_id": str(message.id),
            }
            try:
                for chunk in provider.tts_stream(message.answer.strip()):
                    data = {
                        **common_data,
                        "audio": chunk.get("audio", ""),
                        "sample_rate": chunk.get("sample_rate", 0),
                        "engine": config.engine,
                    }
                    yield f"event: tts_message\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
            except CustomException as error:
                # 业务错误：转成事件，前端提示用户
                payload = {**common_data, "message": getattr(error, "message", "") or "语音合成失败"}
                yield f"event: tts_error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                return
            except Exception as error:  # noqa: BLE001 - 兜底，避免流式过程中裸抛
                logging.error("语音合成异常: %s", error, exc_info=True)
                payload = {**common_data, "message": "语音合成失败，请稍后重试"}
                yield f"event: tts_error\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                return

            yield f"event: tts_end\ndata: {json.dumps({**common_data, 'audio': ''}, ensure_ascii=False)}\n\n"

        return tts()
