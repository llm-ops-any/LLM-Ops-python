#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : __init__.py
@Desc    : 语音 provider 包（CR-16102803）
"""
from .base import (
    BaseAudioProvider,
    create_asr_provider,
    create_tts_provider,
)
from .browser_provider import BROWSER_ENGINE_MESSAGE, BrowserProvider
from .dashscope_provider import DashScopeProvider
from .omni_provider import OmniProvider

__all__ = [
    "BaseAudioProvider",
    "BrowserProvider",
    "OmniProvider",
    "DashScopeProvider",
    "BROWSER_ENGINE_MESSAGE",
    "create_tts_provider",
    "create_asr_provider",
]
