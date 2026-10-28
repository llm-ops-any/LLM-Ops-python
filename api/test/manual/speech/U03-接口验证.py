#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""U-03 验证：经 nginx 打语音接口（配置切换 / 连通性 / ASR）"""
import os
import wave
from array import array

import requests
from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

BASE = "http://llmops-nginx/api"
TOKEN = os.environ["TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
KEY = os.environ["DASHSCOPE_API_KEY"]
TEXT = "今天的天气很好，我们出去走走吧。"


def save_wav16k(pcm24, path):
    source = array("h")
    source.frombytes(pcm24)
    ratio = 24000 / 16000
    out = array("h", (source[int(index * ratio)] for index in range(int(len(source) / ratio))))
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(out.tobytes())


def main():
    print("=== 切到 dashscope 引擎 ===")
    resp = requests.post(
        f"{BASE}/speech-provider",
        headers=HEADERS,
        json={"engine": "dashscope"},
        timeout=20,
    )
    data = resp.json()["data"]
    print(f"  HTTP {resp.status_code} engine={data['engine']} source={data['source']} masked={data['masked_api_key']}")

    print("=== 连通性测试（会合成两个字）===")
    resp = requests.post(f"{BASE}/speech-provider/test", headers=HEADERS, timeout=90)
    print(f"  HTTP {resp.status_code} {resp.json()['data']}")

    print("=== 造一段 16k WAV（CosyVoice 出 24k PCM 再降采样）===")
    synth = SpeechSynthesizer(
        model="cosyvoice-v3-flash",
        voice="longxiaochun_v3",
        format=AudioFormat.PCM_24000HZ_MONO_16BIT,
    )
    pcm = synth.call(TEXT)
    print(f"  PCM 字节={len(pcm)}")
    path = "/tmp/asr_probe.wav"
    save_wav16k(pcm, path)

    print("=== POST /audio/audio-to-text ===")
    with open(path, "rb") as handle:
        files = {"file": ("recording.wav", handle, "audio/wav")}
        resp = requests.post(f"{BASE}/audio/audio-to-text", headers=HEADERS, files=files, timeout=90)
    print(f"  HTTP {resp.status_code} {resp.text[:260]}")

    print("=== engine=browser 时调服务端 ASR（应返回业务提示，不是 5xx）===")
    requests.post(f"{BASE}/speech-provider", headers=HEADERS, json={"engine": "browser"}, timeout=20)
    with open(path, "rb") as handle:
        files = {"file": ("recording.wav", handle, "audio/wav")}
        resp = requests.post(f"{BASE}/audio/audio-to-text", headers=HEADERS, files=files, timeout=30)
    print(f"  HTTP {resp.status_code} {resp.text[:200]}")


if __name__ == "__main__":
    main()
