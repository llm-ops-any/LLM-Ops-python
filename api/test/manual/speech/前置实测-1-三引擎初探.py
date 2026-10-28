#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三引擎语音能力探针：omni（WS 纯朗读）/ cosyvoice-v3.5-flash / paraformer-v2"""
import base64
import io
import json
import os
import struct
import time
import wave

KEY = os.environ["DASHSCOPE_API_KEY"]
HOST = os.environ.get("OMNI_HOST", "dashscope.aliyuncs.com")
TEXT = "README 文档已更新，共三处改动。"


def probe_omni():
    """qwen3.8-omni-flash-realtime：纯文本进 -> PCM 音频出"""
    import websocket

    model = "qwen3.8-omni-flash-realtime"
    url = f"wss://{HOST}/api-ws/v1/realtime?model={model}"
    print(f"\n===== [1] OMNI  {model}  host={HOST} =====")
    try:
        ws = websocket.create_connection(url, header=[f"Authorization: Bearer {KEY}"], timeout=40)
    except Exception as error:
        print("连接失败:", type(error).__name__, str(error)[:200])
        return

    # 等 session.created
    while True:
        event = json.loads(ws.recv())
        if event.get("type") == "error":
            print("建会话失败:", json.dumps(event, ensure_ascii=False)[:300])
            return
        if event.get("type") == "session.created":
            break

    session = {
        "modalities": ["text", "audio"],
        "instructions": "你是一个纯朗读器。逐字朗读用户给出的文本，不要回答、不要改写、不要补充任何前言或语气词。",
        "turn_detection": None,
        "audio": {"output": {"voice": "Aiden", "format": {"type": "pcm", "sample_rate": 24000}}},
    }
    ws.send(json.dumps({"type": "session.update", "session": session}))
    while True:
        event = json.loads(ws.recv())
        if event.get("type") == "error":
            print("会话配置被拒:", json.dumps(event, ensure_ascii=False)[:300])
            return
        if event.get("type") == "session.updated":
            break

    ws.send(
        json.dumps(
            {
                "type": "conversation.item.create",
                "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": TEXT}]},
            }
        )
    )
    started = time.time()
    ws.send(json.dumps({"type": "response.create"}))

    first_packet = None
    chunks = 0
    total = 0
    transcript = ""
    while True:
        event = json.loads(ws.recv())
        etype = event.get("type")
        if etype == "response.audio.delta":
            if first_packet is None:
                first_packet = time.time() - started
            chunks += 1
            total += len(event.get("delta") or "")
        elif etype in ("response.audio_transcript.done", "response.text.done"):
            transcript = event.get("transcript") or event.get("text") or ""
        elif etype == "error":
            print("运行期错误:", json.dumps(event, ensure_ascii=False)[:300])
            break
        elif etype == "response.done":
            break

    # PCM 24k s16le mono -> 秒
    seconds = total * 3 // 4 / 2 / 24000 if total else 0
    print(f"首包延迟 = {first_packet if first_packet is None else round(first_packet, 3)} 秒")
    print(f"音频块数 = {chunks}   base64 总长 = {total}   估算时长 = {round(seconds, 2)} 秒")
    print(f"模型输出文本 = {transcript!r}")
    ws.close()


def probe_cosyvoice():
    """cosyvoice-v3.5-flash：按字符计费的专用 TTS"""
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer

    dashscope.api_key = KEY
    print("\n===== [2] COSYVOICE  cosyvoice-v3.5-flash =====")
    for voice in ["longxiaochun_v2", "longanyang", "longxiaochun", ""]:
        try:
            kwargs = {"model": "cosyvoice-v3.5-flash"}
            if voice:
                kwargs["voice"] = voice
            synth = SpeechSynthesizer(**kwargs)
            started = time.time()
            audio = synth.call(TEXT)
            cost = time.time() - started
            size = len(audio) if audio else 0
            print(f"voice={voice or '(默认)'!r} -> ok 字节={size} 耗时={round(cost, 2)}s")
            if size:
                break
        except Exception as error:
            print(f"voice={voice or '(默认)'!r} -> {type(error).__name__}: {str(error)[:160]}")


def probe_paraformer():
    """paraformer-v2：确认模型可访问（静音 wav 返回空文本也算通）"""
    import dashscope
    from dashscope.audio.asr import Recognition

    dashscope.api_key = KEY
    print("\n===== [3] PARAFORMER  paraformer-realtime-v2 =====")
    path = "/tmp/probe_silence.wav"
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"".join(struct.pack("<h", 0) for _ in range(16000)))
    try:
        started = time.time()
        result = Recognition(model="paraformer-realtime-v2", format="wav", sample_rate=16000).call(file=path)
        cost = time.time() - started
        print(f"status={getattr(result, 'status_code', '?')} 耗时={round(cost, 2)}s")
        print("text =", repr(getattr(result, "output", None) and result.output.get("text")))
    except Exception as error:
        print(f"{type(error).__name__}: {str(error)[:200]}")


if __name__ == "__main__":
    probe_omni()
    probe_cosyvoice()
    probe_paraformer()
