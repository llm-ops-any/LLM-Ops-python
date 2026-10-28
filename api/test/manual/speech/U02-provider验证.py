#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""U-02 验证：三引擎 provider 在容器内直调（不经过 HTTP）"""
import base64
import io
import os
import struct
import time
import wave

from internal.core.audio import create_asr_provider, create_tts_provider
from internal.entity.audio_entity import AudioEngine
from internal.service.speech_provider_service import SpeechProviderConfig

KEY = os.environ["DASHSCOPE_API_KEY"]
HOST = os.environ.get("OMNI_HOST", "dashscope.aliyuncs.com")
TEXT = "今天的天气很好，我们出去走走吧。"


def make_config(engine):
    return SpeechProviderConfig(
        engine=engine,
        api_key=KEY,
        omni_model="qwen3.8-omni-flash-realtime",
        omni_voice="Aiden",
        omni_host=HOST,
        cosyvoice_model="cosyvoice-v3-flash",
        cosyvoice_voice="longxiaochun_v3",
        paraformer_model="paraformer-realtime-v2",
    )


def collect_tts(engine):
    """跑一次 TTS，返回 (块数, 总字节, 首块耗时, PCM 字节)"""
    provider = create_tts_provider(make_config(engine))
    started = time.time()
    first = None
    chunks = 0
    pcm = b""
    for item in provider.tts_stream(TEXT):
        if first is None:
            first = time.time() - started
        chunks += 1
        raw = base64.b64decode(item["audio"])
        pcm += raw
        assert item["sample_rate"] == 24000, item["sample_rate"]
    return chunks, len(pcm), first, pcm


def save_wav(pcm, path, rate=24000):
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm)


def to_16k(pcm, path):
    """24k -> 16k 线性插值，供 Paraformer 使用"""
    from array import array

    source = array("h")
    source.frombytes(pcm)
    ratio = 24000 / 16000
    out = array("h", (source[int(index * ratio)] for index in range(int(len(source) / ratio))))
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(out.tobytes())


if __name__ == "__main__":
    print("=== browser 引擎（应抛业务异常）===")
    try:
        create_tts_provider(make_config(AudioEngine.BROWSER.value)).tts_stream("x")
        print("  ✗ 没有抛异常")
    except Exception as error:
        print(f"  ✓ {type(error).__name__}: {error}")

    print("\n=== omni 引擎 ===")
    chunks, size, first, pcm_omni = collect_tts(AudioEngine.OMNI.value)
    print(f"  块数={chunks} 字节={size} 首块={round(first, 3)}s 时长≈{round(size / 2 / 24000, 2)}s")
    save_wav(pcm_omni, "/tmp/u02_omni.wav")

    print("\n=== dashscope 引擎（CosyVoice）===")
    chunks, size, first, pcm_ds = collect_tts(AudioEngine.DASHSCOPE.value)
    print(f"  块数={chunks} 字节={size} 首块={round(first, 3)}s 时长≈{round(size / 2 / 24000, 2)}s")

    print("\n=== dashscope 引擎（Paraformer ASR 闭环）===")
    to_16k(pcm_ds, "/tmp/u02_asr16k.wav")
    with open("/tmp/u02_asr16k.wav", "rb") as handle:
        content = handle.read()
    provider = create_asr_provider(make_config(AudioEngine.DASHSCOPE.value))
    started = time.time()
    text = provider.asr(content, "recording.wav")
    print(f"  识别 = {text!r}  耗时={round(time.time() - started, 2)}s")
    print("  与原文一致 =", text.replace("，", "").replace("。", "") == TEXT.replace("，", "").replace("。", ""))

    print("\n=== omni 引擎的 ASR 应被拒绝 ===")
    try:
        create_asr_provider(make_config(AudioEngine.OMNI.value)).asr(b"x", "a.wav")
        print("  ✗ 没有抛异常")
    except Exception as error:
        print(f"  ✓ {type(error).__name__}: {error}")
