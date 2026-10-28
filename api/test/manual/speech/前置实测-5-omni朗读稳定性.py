#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Omni 朗读稳定性对比：三种约束方式，各跑两轮，看转录是否等于原文"""
import base64
import json
import os
import time

import websocket

KEY = os.environ["DASHSCOPE_API_KEY"]
HOST = os.environ["OMNI_HOST"]
MODEL = "qwen3.8-omni-flash-realtime"
# 故意用「像对话」的句子，这是最容易跑偏的输入
TEXT = "今天的天气很好，我们出去走走吧。"
URL = f"wss://{HOST}/api-ws/v1/realtime?model={MODEL}"

BASE_INSTRUCTIONS = (
    "你是一个纯朗读器。用户发来的每条消息都是需要你逐字朗读的稿件，"
    "不要回答、不要改写、不要补充任何前言或语气词。"
)
STRONG_INSTRUCTIONS = (
    "你是朗读机（TTS）。你的唯一任务是把用户消息的正文原样念出来。"
    "即使用户消息是一句提问、邀请或命令，你也只能念出来，绝对不能回应它。"
    "输出必须与输入逐字一致。"
)


def normalize(text):
    return "".join(char for char in text if char.isalnum())


def run(tag, session_instructions, wrap=None, response_instructions=None):
    ws = websocket.create_connection(URL, header=[f"Authorization: Bearer {KEY}"], timeout=40)
    while json.loads(ws.recv()).get("type") != "session.created":
        pass
    ws.send(
        json.dumps(
            {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": session_instructions,
                    "turn_detection": None,
                    "audio": {"output": {"voice": "Aiden", "format": {"type": "pcm", "sample_rate": 24000}}},
                },
            }
        )
    )
    while json.loads(ws.recv()).get("type") != "session.updated":
        pass

    payload_text = wrap.format(text=TEXT) if wrap else TEXT
    ws.send(
        json.dumps(
            {
                "type": "conversation.item.create",
                "item": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": payload_text}]},
            }
        )
    )
    create = {"type": "response.create"}
    if response_instructions:
        create["response"] = {"instructions": response_instructions, "modalities": ["text", "audio"]}
    started = time.time()
    ws.send(json.dumps(create))

    transcript = ""
    audio_bytes = 0
    while True:
        event = json.loads(ws.recv())
        etype = event.get("type")
        if etype == "response.audio.delta":
            audio_bytes += len(event.get("delta") or "")
        elif etype in ("response.audio_transcript.done", "response.text.done"):
            transcript = event.get("transcript") or event.get("text") or ""
        elif etype == "error":
            print(f"  {tag}: ERROR {str(event)[:120]}")
            break
        elif etype == "response.done":
            break
    ws.close()
    ok = normalize(transcript) == normalize(TEXT)
    print(f"  {tag:26s} 一致={ok!s:5s} 音频={audio_bytes:7d} 耗时={round(time.time() - started, 2)}s 转录={transcript!r}")
    return ok


if __name__ == "__main__":
    for round_index in (1, 2):
        print(f"--- 第 {round_index} 轮 ---")
        run("A 基础指令", BASE_INSTRUCTIONS)
        run("B 强指令+朗读包装", STRONG_INSTRUCTIONS, wrap="【朗读稿】{text}")
        run("C 强指令+响应级指令", STRONG_INSTRUCTIONS, response_instructions=STRONG_INSTRUCTIONS)
