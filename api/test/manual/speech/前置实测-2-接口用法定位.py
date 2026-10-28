#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""探针 v2：定位 cosyvoice 418 与 paraformer 的 SDK 正确用法"""
import os
import struct
import time
import wave

KEY = os.environ["DASHSCOPE_API_KEY"]
HOST = os.environ.get("OMNI_HOST", "dashscope.aliyuncs.com")
TEXT = "文档已更新。"

import dashscope

dashscope.api_key = KEY


def make_wav(path):
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"".join(struct.pack("<h", 0) for _ in range(16000)))
    return path


def try_cosyvoice(tag, model, voices, base_ws=None):
    from dashscope.audio.tts_v2 import SpeechSynthesizer

    if base_ws:
        dashscope.base_websocket_api_url = base_ws
    print(f"\n--- cosyvoice {model} @ {base_ws or 'default'} ---")
    for voice in voices:
        try:
            synth = SpeechSynthesizer(model=model, voice=voice)
            started = time.time()
            audio = synth.call(TEXT)
            size = len(audio) if audio else 0
            print(f"  voice={voice:22s} 字节={size:7d} 耗时={round(time.time() - started, 2)}s")
            if size:
                return True
        except Exception as error:
            print(f"  voice={voice:22s} {type(error).__name__}: {str(error)[:120]}")
    return False


def try_paraformer_stream(path):
    """paraformer-realtime-v2 是流式回调接口，不是 call(file=)"""
    from dashscope.audio.asr import Recognition, RecognitionCallback

    class Callback(RecognitionCallback):
        def __init__(self):
            self.text = None

        def on_open(self):
            pass

        def on_event(self, result):
            sentence = result.get_sentence()
            if sentence and sentence.get("text"):
                self.text = sentence["text"]

        def on_complete(self):
            pass

        def on_error(self, result):
            print("  on_error:", str(result)[:200])

        def on_close(self):
            pass

    print("\n--- paraformer-realtime-v2 (stream callback) ---")
    callback = Callback()
    try:
        recognition = Recognition(model="paraformer-realtime-v2", format="wav", sample_rate=16000, callback=callback)
        recognition.start()
        with wave.open(path, "rb") as handle:
            handle.readframes(44)
            while True:
                frames = handle.readframes(3200)
                if not frames:
                    break
                recognition.send_audio_frame(frames)
        recognition.stop()
        time.sleep(1)
        print("  text =", repr(callback.text))
    except Exception as error:
        print(f"  {type(error).__name__}: {str(error)[:200]}")


def try_qwen_asr(path):
    """兜底：qwen3-asr-flash 走多模态 HTTP 接口，可直接吃本地文件"""
    print("\n--- qwen3-asr-flash (MultiModalConversation) ---")
    try:
        result = dashscope.MultiModalConversation.call(
            model="qwen3-asr-flash",
            messages=[{"role": "user", "content": [{"audio": f"file://{path}"}]}],
            result_format="message",
        )
        print("  status =", getattr(result, "status_code", "?"))
        print("  output =", str(getattr(result, "output", None))[:300])
    except Exception as error:
        print(f"  {type(error).__name__}: {str(error)[:200]}")


if __name__ == "__main__":
    wav = make_wav("/tmp/probe_silence.wav")
    v2_voices = ["longxiaochun_v2", "longwan_v2", "longcheng_v2", "longhua_v2"]
    v35_voices = ["longxiaochun_v3", "longanyang", "longxiaochun_v2", "Cherry"]

    ok = try_cosyvoice("v35-default", "cosyvoice-v3.5-flash", v35_voices)
    if not ok:
        ok = try_cosyvoice(
            "v35-workspace",
            "cosyvoice-v3.5-flash",
            v35_voices,
            base_ws=f"wss://{HOST}/api-ws/v1/inference",
        )
    if not ok:
        ok = try_cosyvoice("v3-default", "cosyvoice-v3-flash", v35_voices)
    if not ok:
        try_cosyvoice("v2-default", "cosyvoice-v2", v2_voices)

    try_paraformer_stream(wav)
    try_qwen_asr(wav)
