#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : audio_service.py
@Desc    : 语音能力服务（CR-16102803）

职责边界：
- 权限与归属校验（照搬课程原项目逻辑，这部分与平台无关，可直接用）；
- 按配置选 provider 并把结果转成 SSE 文本，provider 内部只管「怎么出声」。
"""
import hashlib
import json
import logging
import os
import pathlib
import time
import uuid
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

# CR-16102809：TTS 合成结果缓存。
# 背景：同一条消息每点一次「朗读」都会重新合成一次、计费一次。
# 存放位置选 storage/（已挂载到宿主机、可写、不进 git），不塞 Redis/数据库——音频体积太大。
TTS_CACHE_DIR = pathlib.Path(__file__).resolve().parents[2] / "storage" / "tts_cache"
TTS_CACHE_TTL_SECONDS = 7 * 24 * 3600     # 7 天：重复听集中在短期，过期清了也无所谓
TTS_CACHE_MAX_BYTES = 20 * 1024 * 1024    # 单文件上限，约 7~8 分钟音频


def _build_tts_cache_key(message: Message, config) -> str:
    """缓存 key：消息 + 引擎 + 音色/模型指纹 + 文本指纹

    为什么要带这么多维度：
    - engine / voice / model 变了必须重新合成，否则会播错人声
    - text_sha 让「消息重新生成后答案变了」自动失效，不用额外做失效逻辑
    """
    answer = (message.answer or "").strip()
    text_sha = hashlib.sha1(answer.encode("utf-8")).hexdigest()[:16]
    voice_raw = f"{getattr(config, 'voice', '')}|{getattr(config, 'model', '')}"
    voice_sha = hashlib.sha1(voice_raw.encode("utf-8")).hexdigest()[:12]
    return f"{message.id}__{getattr(config, 'engine', '')}__{voice_sha}__{text_sha}"


def _load_tts_cache(key: str):
    """读缓存；过期或损坏则删除并返回 None（惰性清理，不引入定时任务）"""
    path = TTS_CACHE_DIR / f"{key}.json"
    try:
        if not path.exists():
            return None
        if time.time() - path.stat().st_mtime > TTS_CACHE_TTL_SECONDS:
            path.unlink(missing_ok=True)
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        chunks = data.get("chunks")
        return chunks if isinstance(chunks, list) and chunks else None
    except Exception:  # noqa: BLE001 - 缓存坏了不该影响主流程
        try:
            path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return None


def _save_tts_cache(key: str, chunks: list) -> None:
    """写缓存：先写临时文件再原子替换，避免并发读到半截 JSON"""
    if not chunks:
        return
    try:
        raw = json.dumps({"chunks": chunks}, ensure_ascii=False).encode("utf-8")
        if len(raw) > TTS_CACHE_MAX_BYTES:
            logging.info("TTS 缓存超出单文件上限(%d 字节)，跳过写入 key=%s", len(raw), key)
            return
        TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        target = TTS_CACHE_DIR / f"{key}.json"
        tmp = TTS_CACHE_DIR / f"{key}.{uuid.uuid4().hex[:8]}.tmp"
        tmp.write_bytes(raw)
        os.replace(tmp, target)
    except Exception as error:  # noqa: BLE001 - 写缓存失败不影响本次播放
        logging.warning("TTS 缓存写入失败 key=%s: %s", key, error)


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

            # CR-16102809：先看有没有可复用的合成结果，命中就不碰 provider（省钱也更快）
            cache_key = _build_tts_cache_key(message, config)
            cached_chunks = _load_tts_cache(cache_key)
            if cached_chunks is not None:
                logging.info("TTS 缓存命中 key=%s chunks=%d", cache_key, len(cached_chunks))
                for item in cached_chunks:
                    data = {**common_data, **item, "engine": config.engine}
                    yield f"event: tts_message\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                yield f"event: tts_end\ndata: {json.dumps({**common_data, 'audio': ''}, ensure_ascii=False)}\n\n"
                return

            # 未命中：边合成边收集；只有完整跑完才落盘
            # 说明：下面两个 except 都 return，用户中途断开时生成器被丢弃，
            #      也不会走到落盘 —— 半截音频不进缓存
            collected: list[dict] = []
            try:
                for chunk in provider.tts_stream(message.answer.strip()):
                    item = {
                        "audio": chunk.get("audio", ""),
                        "sample_rate": chunk.get("sample_rate", 0),
                    }
                    collected.append(item)
                    data = {**common_data, **item, "engine": config.engine}
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

            _save_tts_cache(cache_key, collected)
            yield f"event: tts_end\ndata: {json.dumps({**common_data, 'audio': ''}, ensure_ascii=False)}\n\n"

        return tts()
