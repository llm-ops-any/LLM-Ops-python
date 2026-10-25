#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : _diag_events.py
@Desc    : 诊断脚本 —— 用与 omni_spoken_assistant.py 完全相同的会话配置连服务端，
           边录麦克风边把【所有】原始事件类型打印出来，用来定位「说完了但没回复」。

用法：
    python _diag_events.py
运行后对着麦克风说一句英语，观察 45 秒内打印了哪些事件，然后 Ctrl+C 退出。

关键看这几个事件有没有出现：
    input_audio_buffer.speech_started        -> 服务端 VAD 有没有听到你开口
    input_audio_buffer.speech_stopped        -> 服务端 VAD 有没有判定你说完了
    conversation.item.input_audio_transcription.completed -> 有没有转写出原文
    response.created / response.done         -> 模型有没有生成回复
    出现 error                               -> 直接看报错内容
"""
import asyncio
import base64
import json
import os
import sys
import time
from pathlib import Path

import pyaudio
import websockets
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

INPUT_RATE = 16000
CHUNK_BYTES = 3200

# 与正式脚本保持一致的会话配置
SESSION = {
    "modalities": ["text", "audio"],
    "instructions": "你是英语口语老师，请用中文简洁回复。",
    "turn_detection": {
        "type": os.getenv("VAD_TYPE", "server_vad").strip(),
        "threshold": 0.3,
        "prefix_padding_ms": 300,
        "silence_duration_ms": int(os.getenv("SILENCE_MS", "3000").strip()),
    },
    "input_audio_transcription": {
        "model": "qwen3-asr-flash-realtime",
        "language": os.getenv("ASR_LANGUAGE", "en").strip(),
    },
    "audio": {
        "input": {
            "format": {
                "type": "pcm",
                "sample_rate": INPUT_RATE,
                "sample_format": "s16le",
                "channels": 1,
                "packing": "interleaved",
                "channel_layout": "mono",
            }
        },
        "output": {
            "voice": os.getenv("VOICE", "Aiden").strip(),
            "format": {"type": "pcm", "sample_rate": 24000},
        },
    },
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def main() -> None:
    api_host = os.getenv("API_HOST", "").strip()
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    model = os.getenv("MODEL", "qwen3.8-omni-flash-realtime").strip()
    url = f"wss://{api_host}/api-ws/v1/realtime?model={model}"
    log(f"连接 {url}")

    pya = pyaudio.PyAudio()
    mic = pya.get_default_input_device_info()
    log(f"麦克风: {mic['name']}")
    stream = pya.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=INPUT_RATE,
        input=True,
        frames_per_buffer=CHUNK_BYTES,
    )

    async with websockets.connect(
        url,
        additional_headers={"Authorization": f"Bearer {api_key}"},
        max_size=None,
        open_timeout=20,
    ) as ws:
        while True:
            ev = json.loads(await ws.recv())
            log(f"[S] {ev.get('type')}")
            if ev.get("type") == "session.created":
                log("会话已创建，下发配置原文：")
                log(json.dumps(SESSION, ensure_ascii=False))
                break
            if ev.get("type") == "error":
                log(f"❌ {json.dumps(ev, ensure_ascii=False)}")
                return

        await ws.send(json.dumps({"type": "session.update", "session": SESSION}))
        while True:
            ev = json.loads(await ws.recv())
            log(f"[S] {ev.get('type')}  {json.dumps(ev, ensure_ascii=False)[:400]}")
            if ev.get("type") == "session.updated":
                break
            if ev.get("type") == "error":
                log("❌ session.update 被拒")
                return

        log("✅ 初始化完成，请现在对着麦克风说一句英语（最多观察 45 秒）")

        async def send_audio() -> None:
            loop = asyncio.get_event_loop()
            while True:
                data = await loop.run_in_executor(
                    None, lambda: stream.read(CHUNK_BYTES, exception_on_overflow=False)
                )
                await ws.send(json.dumps({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(data).decode("ascii"),
                }))

        async def recv_events() -> None:
            deadline = time.time() + 45
            while time.time() < deadline:
                ev = json.loads(await asyncio.wait_for(
                    ws.recv(), timeout=max(deadline - time.time(), 1)
                ))
                etype = ev.get("type")
                extra = ""
                if etype == "conversation.item.input_audio_transcription.completed":
                    extra = f" -> 转写: {ev.get('transcript')!r}"
                elif etype in ("response.audio_transcript.delta", "response.text.delta"):
                    extra = f" -> {ev.get('delta')!r}"
                elif etype == "response.done":
                    extra = f" -> status={ev.get('response', {}).get('status')}"
                elif etype == "response.audio.delta":
                    extra = f" -> {len(base64.b64decode(ev['delta']))} 字节音频"
                elif etype == "error":
                    extra = f" -> {json.dumps(ev, ensure_ascii=False)[:500]}"
                log(f"[S] {etype}{extra}")

        await asyncio.gather(send_audio(), recv_events())

    log("45 秒观察结束")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n已退出")
