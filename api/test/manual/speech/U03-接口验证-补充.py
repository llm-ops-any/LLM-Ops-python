#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""U-03 验证补充：缓存 TTL 后的 browser 分支 + message-to-audio 全链路"""
import json
import os
import time
import wave

import requests

BASE = "http://llmps-nginx/api".replace("llmps", "llmops")
TOKEN = os.environ["TOKEN"]
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


def sse_collect(message_id, limit=3):
    """调 SSE 接口，收前若干个事件"""
    events = []
    with requests.post(
        f"{BASE}/audio/message-to-audio",
        headers=HEADERS,
        json={"message_id": message_id},
        stream=True,
        timeout=120,
    ) as resp:
        if resp.status_code != 200:
            return resp.status_code, [], resp.text[:200]
        buffer = ""
        for raw in resp.iter_lines(decode_unicode=True):
            if raw is None:
                continue
            line = raw.strip()
            if line.startswith("event:"):
                buffer = line[6:].strip()
            elif line.startswith("data:"):
                events.append((buffer, line[5:].strip()))
                if len(events) >= limit:
                    break
    return 200, events, ""


def main():
    print("=== 等过缓存 TTL 后再测 browser 分支 ===")
    time.sleep(7)
    wav_path = "/tmp/asr_probe.wav"
    with open(wav_path, "rb") as handle:
        files = {"file": ("recording.wav", handle, "audio/wav")}
        resp = requests.post(f"{BASE}/audio/audio-to-text", headers=HEADERS, files=files, timeout=30)
    print(f"  HTTP {resp.status_code} {resp.text[:200]}")

    print("=== 切回 dashscope ===")
    requests.post(f"{BASE}/speech-provider", headers=HEADERS, json={"engine": "dashscope"}, timeout=20)
    time.sleep(7)

    print("=== 找一个调试消息并临时开启该应用的 TTS ===")
    from app.http.app import app as flask_app
    from app.http.module import injector
    from internal.model import App, AppConfigVersion, Message
    from pkg.sqlalchemy import SQLAlchemy

    with flask_app.app_context():
        db = injector.get(SQLAlchemy)
        message = (
            db.session.query(Message)
            .filter(Message.invoke_from == "debugger")
            .filter(Message.answer != "")
            .order_by(Message.created_at.desc())
            .first()
        )
        if message is None:
            print("  没有找到可用的调试消息，跳过")
            return
        app_row = db.session.query(App).get(message.app_id)
        config = app_row.draft_app_config
        original = dict(config.text_to_speech or {})
        config.text_to_speech = {**original, "enable": True}
        db.session.commit()
        message_id = str(message.id)
        answer_head = message.answer[:30]
        print(f"  message_id={message_id} 答案开头={answer_head!r}")
        print(f"  原 text_to_speech={original} 已临时改为 enable=True")

    try:
        status, events, error = sse_collect(message_id)
        print(f"=== POST /audio/message-to-audio -> HTTP {status} ===")
        if events:
            name, data = events[0]
            payload = json.loads(data)
            print(f"  event={name} audio_len={len(payload.get('audio') or '')} sample_rate={payload.get('sample_rate')}")
            print(f"  事件总数(前{len(events)}个)={[item[0] for item in events]}")
        else:
            print("  无事件:", error)
    finally:
        with flask_app.app_context():
            db = injector.get(SQLAlchemy)
            config = db.session.query(AppConfigVersion).get(
                db.session.query(App).get(message.app_id).draft_app_config_id
            )
            config.text_to_speech = original
            db.session.commit()
            print(f"=== 已还原 text_to_speech={original} ===")


if __name__ == "__main__":
    main()
