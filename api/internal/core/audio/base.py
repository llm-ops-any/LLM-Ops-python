#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : base.py
@Desc    : 语音 provider 抽象与工厂（CR-16102803 / D-01）

抽象边界：
- TTS 统一产出 {"audio": <base64 PCM>, "sample_rate": int} 的迭代器，handler 直接转 SSE；
- ASR 统一吃「文件字节 + 文件名」，返回文本；
- 不支持的能力抛 FailException（业务错误，不是 5xx），由 handler 转成 code≠success。
"""
from typing import Generator

from internal.entity.audio_entity import AudioEngine


class BaseAudioProvider:
    """语音 provider 基类"""
    name: str = ""
    supports_tts: bool = False
    supports_asr: bool = False

    def tts_stream(self, text: str) -> Generator[dict, None, None]:
        """把文本合成成音频块，逐块 yield {"audio": base64, "sample_rate": int}"""
        raise NotImplementedError

    def asr(self, content: bytes, filename: str) -> str:
        """把音频字节识别成文本"""
        raise NotImplementedError


def create_tts_provider(config) -> BaseAudioProvider:
    """按配置创建 TTS provider

    说明：延迟导入，避免 providers 与 service 包之间的循环导入。
    """
    if config.engine == AudioEngine.OMNI.value:
        from .omni_provider import OmniProvider

        return OmniProvider(config)
    if config.engine == AudioEngine.DASHSCOPE.value:
        from .dashscope_provider import DashScopeProvider

        return DashScopeProvider(config)

    from .browser_provider import BrowserProvider

    return BrowserProvider(config)


def create_asr_provider(config) -> BaseAudioProvider:
    """按配置创建 ASR provider

    CR-16102803 / D-08：服务端 ASR 只在 dashscope 档提供。
    omni 档虽然模型本身能识别语音，但需要上行音频流（实时对话形态），不在本 CR 范围；
    因此 omni 档的识别由前端浏览器完成。
    """
    if config.engine == AudioEngine.DASHSCOPE.value:
        from .dashscope_provider import DashScopeProvider

        return DashScopeProvider(config)

    from .browser_provider import BrowserProvider

    return BrowserProvider(config)
