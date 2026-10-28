#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""验证 cosyvoice-v3-flash 是否真的在合成：合成 -> 落盘 -> ASR 转回 -> 比对文本"""
import os
import time
import wave

import dashscope

KEY = os.environ["DASHSCOPE_API_KEY"]
dashscope.api_key = KEY
TEXT = "今天的天气很好，我们出去走走吧。"


def list_voices():
    """查该账号实际可用的音色（能列出什么就说明有什么授权）"""
    print("=== 音色清单 ===")
    try:
        from dashscope.audio.tts_v2 import VoiceEnrollmentService

        service = VoiceEnrollmentService()
        for name in ("list_voices", "query_voices"):
            if hasattr(service, name):
                try:
                    result = getattr(service, name)()
                    print(f"  {name}() ->", str(result)[:800])
                except Exception as error:
                    print(f"  {name}() 失败: {type(error).__name__}: {str(error)[:200]}")
    except Exception as error:
        print("  VoiceEnrollmentService 不可用:", type(error).__name__, str(error)[:200])


def synth():
    """合成并落盘，返回文件路径"""
    from dashscope.audio.tts_v2 import SpeechSynthesizer

    print("\n=== 合成 ===")
    synth_obj = SpeechSynthesizer(model="cosyvoice-v3-flash", voice="longxiaochun_v3")
    started = time.time()
    audio = synth_obj.call(TEXT)
    cost = time.time() - started
    if not audio:
        print("  返回 0 字节 —— 合成失败")
        return None
    path = "/tmp/cosyvoice_check.mp3"
    with open(path, "wb") as handle:
        handle.write(audio)
    head = audio[:16]
    print(f"  字节数 = {len(audio)}  耗时 = {round(cost, 2)}s")
    print(f"  头 16 字节 = {head!r}  (ID3 开头即 mp3)")
    # mp3 128kbps 粗略估时长
    print(f"  估算时长 ≈ {len(audio) / 16000:.2f} 秒（按 128kbps mp3 粗算）")
    return path


def transcribe(path):
    """用另一条链路把音频转回文本，验证内容真伪"""
    print("\n=== 回灌 ASR（闭环校验）===")
    started = time.time()
    result = dashscope.MultiModalConversation.call(
        model="qwen3-asr-flash",
        messages=[{"role": "user", "content": [{"audio": f"file://{path}"}]}],
        result_format="message",
    )
    content = result.output["choices"][0]["message"]["content"]
    text = "".join(part.get("text", "") for part in content) if isinstance(content, list) else content
    print(f"  ASR 转回 = {text!r}   耗时 = {round(time.time() - started, 2)}s")
    print(f"  原文     = {TEXT!r}")
    normal = lambda value: "".join(ch for ch in value if ch not in "，。,.")
    print("  一致 =", normal(text or "") == normal(TEXT))
    return text


if __name__ == "__main__":
    list_voices()
    path = synth()
    if path:
        transcribe(path)
