#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : browser_provider.py
@Desc    : 浏览器引擎（CR-16102803 / D-02）

行为：后端不参与合成 —— 录音与播放都由浏览器完成（Web Speech API + SpeechSynthesis）。
若前端误调服务端接口，返回明确业务提示而不是 5xx（AC-07）。
"""
from typing import Generator

from internal.exception import FailException
from .base import BaseAudioProvider

# 统一提示语，前端可直接展示
BROWSER_ENGINE_MESSAGE = "当前语音引擎由浏览器执行，无需调用服务端语音接口"


class BrowserProvider(BaseAudioProvider):
    """浏览器引擎 provider（占位实现）"""
    name = "browser"
    supports_tts = False
    supports_asr = False

    def __init__(self, config=None) -> None:
        self.config = config

    def tts_stream(self, text: str) -> Generator[dict, None, None]:
        raise FailException(BROWSER_ENGINE_MESSAGE)

    def asr(self, content: bytes, filename: str) -> str:
        raise FailException(BROWSER_ENGINE_MESSAGE)
