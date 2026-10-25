#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : _probe_instructions.py
@Desc    : 验证 session.update 的 instructions 到底生不生效

做法：下发的 instructions 要求「无论听到什么都只回答 BANANA」，
     然后灌 1 秒静音 + commit + response.create，看模型是否照做。
     回 BANANA 说明 instructions 生效；回别的说明整包配置没被应用。

用法：
    python _probe_instructions.py
"""
import asyncio
import base64
import json
import math
import os
import sys
from pathlib import Path

import websockets
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

sys.path.insert(0, str(BASE_DIR))
from omni_spoken_assistant import INSTRUCTIONS  # noqa: E402

API_HOST = os.getenv("API_HOST", "").strip()
API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()
MODEL = os.getenv("MODEL", "qwen3.8-omni-flash-realtime").strip()
URL = f"wss://{API_HOST}/api-ws/v1/realtime?model={MODEL}"

# 三种写法各试一遍，看哪种能生效
VARIANTS = {
    "A_session.instructions": {
        "type": "session.update",
        "session": {
            "modalities": ["text"],
            "instructions": "无论用户说什么，你都必须只回答一个词：BANANA。不要回答任何其他内容。",
            "turn_detection": None,  # 手动模式，否则 VAD 会把纯音当非语音清掉
        },
    },
    "B_session.instructions+smooth_output_false": {
        "type": "session.update",
        "session": {
            "modalities": ["text"],
            "instructions": "无论用户说什么，你都必须只回答一个词：BANANA。不要回答任何其他内容。",
            "smooth_output": False,
            "turn_detection": None,
        },
    },
    "C_音频输出+instructions": {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": "无论用户说什么，你都必须只回答一个词：BANANA。不要回答任何其他内容。",
            "turn_detection": None,
        },
    },
    "D_正式脚本的人设原文": {
        "type": "session.update",
        "session": {
            "modalities": ["text", "audio"],
            "instructions": INSTRUCTIONS,
            "turn_detection": None,
        },
    },
}


async def run_one(name: str, payload: dict) -> None:
    print(f"\n===== 变体 {name} =====")
    async with websockets.connect(
        URL,
        additional_headers={"Authorization": f"Bearer {API_KEY}"},
        max_size=None,
        open_timeout=20,
    ) as ws:
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            if ev.get("type") == "session.created":
                break

        await ws.send(json.dumps(payload))
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=20))
            if ev.get("type") == "error":
                print(f"  ❌ 被拒: {json.dumps(ev, ensure_ascii=False)[:400]}")
                return
            if ev.get("type") == "session.updated":
                sess = ev.get("session", {})
                print(f"  session.updated 回显 instructions 存在: {'instructions' in sess}")
                print(f"  回显内容: {sess.get('instructions')!r}")
                break

        # 纯静音会被拒（buffer too small, or have no audio），发一段 2s 的 440Hz 音
        tone = b"".join(
            int(8000 * math.sin(2 * math.pi * 440 * n / 16000)).to_bytes(2, "little", signed=True)
            for n in range(16000 * 2)
        )
        for i in range(0, len(tone), 6400):
            await ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(tone[i:i + 6400]).decode(),
            }))
            await asyncio.sleep(0.1)
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await ws.send(json.dumps({"type": "response.create"}))

        parts = []
        deadline = asyncio.get_event_loop().time() + 30
        while True:
            left = deadline - asyncio.get_event_loop().time()
            if left <= 0:
                print("  ⏱️ 超时")
                break
            ev = json.loads(await asyncio.wait_for(ws.recv(), timeout=left))
            et = ev.get("type")
            if et in ("response.text.delta", "response.audio_transcript.delta"):
                parts.append(ev.get("delta", ""))
            elif et in ("response.text.done", "response.audio_transcript.done"):
                parts.append(ev.get("text") or ev.get("transcript") or "")
            elif et == "response.done":
                break
            elif et == "error":
                print(f"  ❌ {json.dumps(ev, ensure_ascii=False)[:400]}")
                break

        reply = "".join(parts).strip()
        verdict = "✅ instructions 生效" if "BANANA" in reply.upper() else "❌ instructions 未生效"
        print(f"  模型回复: {reply!r}")
        print(f"  判定: {verdict}")


async def main() -> None:
    for name, payload in VARIANTS.items():
        await run_one(name, payload)


if __name__ == "__main__":
    asyncio.run(main())
