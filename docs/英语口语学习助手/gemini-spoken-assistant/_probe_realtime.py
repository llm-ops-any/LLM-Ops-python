#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : _probe_realtime.py
@Desc    : 连通性探测脚本 —— 只验证「地址 + 密钥 + 协议」能不能通，不做业务逻辑

用法：
    python _probe_realtime.py

成功标志：
    1. 收到 session.created
    2. 收到 session.updated（说明 session.update 的字段结构被接受）
    3. response.done 且 status 正常
"""
import asyncio
import base64
import json
import os
import sys
from pathlib import Path

import websockets
from dotenv import load_dotenv

# Windows 控制台默认 GBK，中文/表情会抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

API_HOST = os.getenv("API_HOST")
API_KEY = os.getenv("DASHSCOPE_API_KEY")
MODEL = os.getenv("MODEL", "qwen3.8-omni-flash-realtime")
VOICE = os.getenv("VOICE", "Ethan")

URL = f"wss://{API_HOST}/api-ws/v1/realtime?model={MODEL}"

SESSION_UPDATE = {
    "type": "session.update",
    "session": {
        "modalities": ["text", "audio"],
        "voice": VOICE,
        "instructions": "你是英语口语老师，请用中文简洁回复。",
        "turn_detection": None,  # 探测用手动模式，避免环境噪音触发
        "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
        "audio": {
            "input": {
                "format": {
                    "type": "pcm",
                    "sample_rate": 16000,
                    "sample_format": "s16le",
                    "channels": 1,
                    "packing": "interleaved",
                    "channel_layout": "mono",
                }
            },
            "output": {
                "voice": VOICE,
                "format": {"type": "pcm", "sample_rate": 24000},
            },
        },
    },
}


async def main() -> None:
    print(f"→ 连接 {URL}")
    async with websockets.connect(
        URL,
        additional_headers={"Authorization": f"Bearer {API_KEY}"},
        max_size=None,
        open_timeout=15,
    ) as ws:
        # 1. 等 session.created
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            print(f"[S] {event.get('type')}")
            if event["type"] == "error":
                print("❌ 服务端报错：", json.dumps(event, ensure_ascii=False))
                return
            if event["type"] == "session.created":
                break

        # 2. 下发会话配置，等服务端确认
        await ws.send(json.dumps(SESSION_UPDATE))
        print("[C] session.update 已发送")
        while True:
            event = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            print(f"[S] {event.get('type')}")
            if event["type"] == "error":
                print("❌ session.update 被拒：", json.dumps(event, ensure_ascii=False))
                return
            if event["type"] == "session.updated":
                break

        # 3. 灌 1 秒静音（16kHz/16bit/单声道 → 32000 字节，按 3200 字节分 10 帧）
        silence = b"\x00" * 3200
        for _ in range(10):
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(silence).decode(),
            }))
            await asyncio.sleep(0.1)
        print("[C] 已发送 1s 静音音频")

        # 4. 手动提交并请求生成
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await ws.send(json.dumps({"type": "response.create"}))

        # 5. 收结果
        pcm_path = BASE_DIR / "probe_reply.pcm"
        audio_bytes = 0
        text_parts = []
        deadline = asyncio.get_event_loop().time() + 30
        with open(pcm_path, "wb") as f:
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    print("⏱️ 30s 超时，未收到 response.done")
                    break
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
                etype = event.get("type")
                if etype == "error":
                    print("❌ 服务端报错：", json.dumps(event, ensure_ascii=False))
                    break
                if etype == "response.audio.delta":
                    chunk = base64.b64decode(event["delta"])
                    f.write(chunk)
                    audio_bytes += len(chunk)
                elif etype in ("response.audio_transcript.delta", "response.text.delta"):
                    text_parts.append(event.get("delta", ""))
                elif etype == "conversation.item.input_audio_transcription.completed":
                    print(f"[S] 用户原文转写：{event.get('transcript')!r}")
                elif etype == "response.done":
                    print(f"✅ response.done status={event.get('response', {}).get('status')}")
                    break
                else:
                    print(f"[S] {etype}")

    print("\n===== 探测结果 =====")
    print(f"助手文本：{''.join(text_parts)!r}")
    print(f"音频字节：{audio_bytes}（{audio_bytes / 2 / 24000:.2f} 秒 @24kHz）")
    print(f"音频文件：{pcm_path}")


if __name__ == "__main__":
    asyncio.run(main())
