#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""探针 v3：CosyVoice 音频格式选项 + 用 Omni 生成的真实语音回灌 ASR"""
import base64
import json
import os
import time
import wave
from array import array

import dashscope
import websocket

KEY = os.environ["DASHSCOPE_API_KEY"]
HOST = os.environ.get("OMNI_HOST", "dashscope.aliyuncs.com")
dashscope.api_key = KEY

SPOKEN = "今天的天气很好，我们出去走走吧。"


def omni_tts(text, path):
    """用 Omni 把文本念出来，PCM 24k 落盘，返回 wav 路径"""
    url = f"wss://{HOST}/api-ws/v1/realtime?model=qwen3.8-omni-flash-realtime"
    ws = websocket.create_connection(url, header=[f"Authorization: Bearer {KEY}"], timeout=40)
    while json.loads(ws.recv()).get("type") != "session.created":
        pass
    ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": "你是一个纯朗读器。逐字朗读用户给出的文本，不要回答、不要改写。",
                    "turn_detection": None,
                    "audio": {"output": {"voice": "Aiden", "format": {"type": "pcm", "sample_rate": 24000}}},
                },
            }
        )
    )
    while json.loads(ws.recv()).get("type") != "session.updated":
        pass
    ws.send(
        json.dumps(
            {
                "type": "conversation.item.create",
                "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]},
            }
        )
    )
    ws.send(json.dumps({"type": "response.create"}))
    pcm = b""
    while True:
        event = json.loads(ws.recv())
        if event.get("type") == "response.audio.delta":
            pcm += base64.b64decode(event["delta"])
        elif event.get("type") == "response.done":
            break
    ws.close()
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(pcm)
    print(f"Omni 生成 PCM 24k: {len(pcm)} 字节 ≈ {len(pcm) / 2 / 24000:.2f} 秒 -> {path}")
    return path


def resample_16k(src, dst):
    """24k -> 16k 线性插值重采样（只为测试，产品侧用前端 16k 采集）"""
    with wave.open(src, "rb") as handle:
        frames = array("h")
        frames.frombytes(handle.readframes(handle.getnframes()))
    ratio = 24000 / 16000
    out = array("h", (frames[int(index * ratio)] for index in range(int(len(frames) / ratio))))
    with wave.open(dst, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(out.tobytes())
    print(f"重采样 16k -> {dst}")


def probe_paraformer(path):
    print("\n--- paraformer-realtime-v2 ---")
    from dashscope.audio.asr import Recognition, RecognitionCallback

    class Callback(RecognitionCallback):
        def __init__(self):
            self.texts = []

        def on_open(self):
            pass

        def on_event(self, result):
            sentence = result.get_sentence()
            if sentence and sentence.get("text"):
                self.texts.append(sentence["text"])

        def on_complete(self):
            pass

        def on_error(self, result):
            print("  on_error:", str(result)[:200])

        def on_close(self):
            pass

    callback = Callback()
    try:
        recognition = Recognition(
            model="paraformer-realtime-v2", format="wav", sample_rate=16000, callback=callback
        )
        recognition.start()
        with wave.open(path, "rb") as handle:
            while True:
                frames = handle.readframes(1600)
                if not frames:
                    break
                recognition.send_audio_frame(frames)
        recognition.stop()
        time.sleep(1.5)
        print("  识别结果 =", repr("".join(callback.texts)))
    except Exception as error:
        print(f"  {type(error).__name__}: {str(error)[:200]}")


def probe_qwen_asr(path):
    print("\n--- qwen3-asr-flash ---")
    started = time.time()
    result = dashscope.MultiModalConversation.call(
        model="qwen3-asr-flash",
        messages=[{"role": "user", "content": [{"audio": f"file://{path}"}]}],
        result_format="message",
    )
    content = result.output["choices"][0]["message"]["content"]
    text = "".join(part.get("text", "") for part in content) if isinstance(content, list) else content
    print(f"  识别结果 = {text!r}   耗时={round(time.time() - started, 2)}s")


def probe_formats():
    print("\n--- CosyVoice 可用音频格式 ---")
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

    formats = [name for name in dir(AudioFormat) if name.isupper()]
    print("  AudioFormat:", formats)
    for name in formats:
        if "PCM" not in name:
            continue
        try:
            synth = SpeechSynthesizer(model="cosyvoice-v3-flash", voice="longxiaochun_v3", format=AudioFormat[name])
            audio = synth.call("测试")
            head = audio[:4] if audio else b""
            print(f"  {name:34s} 字节={len(audio) if audio else 0:6d} 头={head!r}")
        except Exception as error:
            print(f"  {name:34s} {type(error).__name__}: {str(error)[:80]}")


if __name__ == "__main__":
    wav24 = omni_tts(SPOKEN, "/tmp/omni_tts_24k.wav")
    wav16 = "/tmp/omni_tts_16k.wav"
    resample_16k(wav24, wav16)
    probe_paraformer(wav16)
    probe_qwen_asr(wav24)
    probe_formats()
