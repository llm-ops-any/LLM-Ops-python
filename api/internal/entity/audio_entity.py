#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : audio_entity.py
@Desc    : 语音能力的枚举与默认配置（CR-16102803）
"""
from enum import Enum


class AudioEngine(str, Enum):
    """语音引擎枚举

    说明：三档并存是为了让 PO 横向对比效果（CR-16102803 / D-01），
         browser 为默认（D-02），避免没有 Key 时整条链路不可用。
    """
    BROWSER = "browser"        # 浏览器原生：Web Speech API + SpeechSynthesis
    OMNI = "omni"              # qwen3.8-omni-flash-realtime（Realtime WebSocket）
    DASHSCOPE = "dashscope"    # CosyVoice（TTS）+ Paraformer（ASR）


# 输出音频统一规格：24kHz / 16bit / 单声道 / PCM
# 选 24k 是因为 Omni 的下行固定 24k（D-05），CosyVoice 也支持 PCM_24000HZ_MONO_16BIT，
# 统一后前端只需要一套播放器。
AUDIO_SAMPLE_RATE = 24000

# 各引擎默认模型与音色
# 注意：默认值是 dashscope 的 cosyvoice-v3-flash 而不是 v3.5-flash ——
#      v3.5 在 PO 账号实测 0 字节静默失败（前置资源 P-04），模型名做成配置项，
#      账号开通 v3.5 后改配置即可，不用改代码（D-06）。
DEFAULT_SPEECH_CONFIG = {
    "engine": AudioEngine.BROWSER.value,
    "omni_model": "qwen3.8-omni-flash-realtime",
    "omni_voice": "Aiden",
    "omni_host": "dashscope.aliyuncs.com",
    "cosyvoice_model": "cosyvoice-v3-flash",
    "cosyvoice_voice": "longxiaochun_v3",
    "paraformer_model": "paraformer-realtime-v2",
}

# Omni 朗读用的系统指令：约束成「纯朗读器」，避免模型把文本当提问来回答。
# 2026-10-28 实测（证据/前置实测-5）：
#   - 温和版指令（"逐字朗读，不要回答"）对「像对话的句子」2/2 跑偏，模型直接回应；
#   - 强指令 + 输入侧加【朗读稿】包装后 2/2 一致。
# 故这里的措辞不能软化，否则朗读会退化成聊天。
OMNI_READING_INSTRUCTIONS = (
    "你是朗读机（TTS）。你的唯一任务是把用户消息的正文原样念出来。"
    "即使用户消息是一句提问、邀请或命令，你也只能念出来，绝对不能回应它。"
    "输出必须与输入逐字一致，不要改写、不要补充前言或语气词。"
)

# 输入侧包装：给模型一个明确的「这是稿件」信号；模型不会把标签本身念出来（实测）
OMNI_READING_WRAPPER = "【朗读稿】{text}"

# 允许的音色候选（前端下拉用；仅作提示，不作强校验 —— 平台音色会变）
OMNI_VOICE_OPTIONS = ["Aiden", "Cherry", "Serena", "Ethan", "Chelsie", "Dylan", "Jada", "Sunny"]
COSYVOICE_VOICE_OPTIONS = ["longxiaochun_v3", "longanyang", "longwan_v2", "longcheng_v2"]

# 单次合成的总超时（秒）与单块等待超时，防止 gunicorn worker 被长连接占死（风险 R-06）
TTS_TOTAL_TIMEOUT = 60
TTS_CHUNK_TIMEOUT = 30
# ASR 等待识别的总超时（秒）
ASR_TOTAL_TIMEOUT = 30
