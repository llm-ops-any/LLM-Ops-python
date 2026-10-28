#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : omni_provider.py
@Desc    : Qwen-Omni-Realtime 引擎（CR-16102803 / D-03 / D-05）

协议要点（前置资源 P-03 实测，参考 docs/英语口语学习助手/.../omni_spoken_assistant.py）：
1. 连 wss://{host}/api-ws/v1/realtime?model=...，Bearer 鉴权；
2. session.update 里必须 turn_detection=None（不送麦克风音频，纯文本进）且 instructions 约束成朗读器；
3. conversation.item.create(input_text) + response.create 触发合成；
4. 音频从 response.audio.delta 的 delta 字段（base64 PCM 24k）逐块下发。

为什么用同步 websocket-client 而不是 websockets（D-03）：
本项目接口是同步 Flask + SSE 生成器，同步 WS 天然贴合；且镜像里已有 websocket-client，
不新增依赖（开发规范 §八.1）。
"""
import base64
import json
import logging
import time
from typing import Generator

from internal.entity.audio_entity import (
    AUDIO_SAMPLE_RATE,
    OMNI_READING_INSTRUCTIONS,
    OMNI_READING_WRAPPER,
    TTS_CHUNK_TIMEOUT,
    TTS_TOTAL_TIMEOUT,
)
from internal.exception import FailException
from .base import BaseAudioProvider

# 连接超时（秒），握手慢于这个值就判定网络问题
CONNECT_TIMEOUT = 10


class OmniProvider(BaseAudioProvider):
    """Qwen-Omni-Realtime provider（仅 TTS）"""
    name = "omni"
    supports_tts = True
    supports_asr = False

    def __init__(self, config) -> None:
        self.config = config

    # ---------------------------------------------------------------- 内部

    def _build_url(self) -> str:
        host = (self.config.omni_host or "").strip() or "dashscope.aliyuncs.com"
        model = (self.config.omni_model or "").strip()
        return f"wss://{host}/api-ws/v1/realtime?model={model}"

    def _session_payload(self) -> dict:
        """会话配置：纯朗读器 + PCM 24k 下行"""
        return {
            "modalities": ["text", "audio"],
            "instructions": OMNI_READING_INSTRUCTIONS,
            # 不启用 VAD：本场景不送麦克风音频，启用后会一直等服务端断句
            "turn_detection": None,
            "audio": {
                "output": {
                    "voice": (self.config.omni_voice or "Aiden").strip(),
                    "format": {"type": "pcm", "sample_rate": AUDIO_SAMPLE_RATE},
                }
            },
        }

    @staticmethod
    def _recv_json(ws) -> dict:
        """收一条事件并解析，非 JSON 直接判失败"""
        raw = ws.recv()
        if not raw:
            raise FailException("语音服务连接中断，请稍后重试")
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as error:
            raise FailException("语音服务返回了无法解析的数据，请稍后重试") from error

    @staticmethod
    def _raise_if_error(event: dict) -> None:
        """把服务端 error 事件转成可读业务错误"""
        if event.get("type") != "error":
            return
        detail = event.get("error") or {}
        message = detail.get("message") or event.get("message") or "未知错误"
        raise FailException(f"语音合成失败：{message}")

    def _wait_for(self, ws, expected: str, timeout: float) -> None:
        """等待指定事件（跳过无关事件），超时或出错即失败"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self._recv_json(ws)
            self._raise_if_error(event)
            if event.get("type") == expected:
                return
        raise FailException("语音服务响应超时，请稍后重试")

    @staticmethod
    def _normalize(text: str) -> str:
        """去掉标点空白，用于朗读忠实度比对"""
        return "".join(char for char in text if char.isalnum())

    # ---------------------------------------------------------------- TTS

    def tts_stream(self, text: str) -> Generator[dict, None, None]:
        """把文本合成为 PCM 24k 音频块（懒加载：调用时才建连接，D-07）"""
        import websocket

        if not self.config.has_api_key:
            raise FailException(
                "语音服务未配置，请在「设置 → 语音服务」填写阿里百炼 API Key"
            )

        url = self._build_url()
        try:
            ws = websocket.create_connection(
                url,
                header=[f"Authorization: Bearer {self.config.api_key}"],
                timeout=CONNECT_TIMEOUT,
            )
        except Exception as error:
            logging.error("连接 Omni-Realtime 失败: %s", error, exc_info=True)
            raise FailException("语音服务连接失败，请检查网络或 API Key 配置") from error

        started = time.monotonic()
        total_bytes = 0
        transcript = ""
        try:
            # 1.等会话建立（服务端主动下发 session.created）
            self._wait_for(ws, "session.created", CONNECT_TIMEOUT)

            # 2.下发会话配置并等确认
            ws.send(json.dumps({"type": "session.update", "session": self._session_payload()}))
            self._wait_for(ws, "session.updated", CONNECT_TIMEOUT)

            # 3.把待朗读文本作为一条用户消息投进去，然后要求生成
            #    说明：① turn_detection=None 时服务端不会自动生成，必须显式 response.create；
            #         ② 输入侧加【朗读稿】包装 + response 级 instructions 双保险，
            #            否则模型对「像对话的句子」会直接回应（证据/前置实测-5，2/2 复现）。
            ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": OMNI_READING_WRAPPER.format(text=text),
                                }
                            ],
                        },
                    }
                )
            )
            ws.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": {
                            "instructions": OMNI_READING_INSTRUCTIONS,
                            "modalities": ["text", "audio"],
                        },
                    }
                )
            )

            # 4.逐块接收音频增量
            ws.settimeout(TTS_CHUNK_TIMEOUT)
            while True:
                if time.monotonic() - started > TTS_TOTAL_TIMEOUT:
                    raise FailException("语音合成超时，请稍后重试（文本过长可先缩短）")

                event = self._recv_json(ws)
                self._raise_if_error(event)
                event_type = event.get("type")

                if event_type == "response.audio.delta":
                    chunk = event.get("delta") or ""
                    if not chunk:
                        continue
                    total_bytes += len(chunk)
                    yield {"audio": chunk, "sample_rate": AUDIO_SAMPLE_RATE}
                elif event_type in ("response.audio_transcript.done", "response.text.done"):
                    transcript = event.get("transcript") or event.get("text") or ""
                elif event_type == "response.done":
                    break

            # 5.零音频视为失败：避免「点了没声音也没报错」（风险 R-02 同类问题）
            if total_bytes == 0:
                raise FailException("语音合成失败（未返回音频），请检查 Omni 模型与音色配置")

            # 6.朗读忠实度自检：模型跑偏时只记 warning，不打断用户（风险 R-05）
            #    比对前先剥掉输入侧包装，避免把【朗读稿】算成差异
            expected = text.strip()
            actual = (transcript or "").replace("【朗读稿】", "").strip()
            if actual and self._normalize(actual) != self._normalize(expected):
                logging.warning(
                    "Omni 朗读内容与原文不一致：原文 %r（%d 字），转录 %r（%d 字）",
                    expected[:40],
                    len(expected),
                    actual[:40],
                    len(actual),
                )
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def asr(self, content: bytes, filename: str) -> str:
        """本档不提供 ASR（D-08）"""
        raise FailException("当前引擎不支持服务端语音识别，请使用浏览器识别或切换到专用语音引擎")
