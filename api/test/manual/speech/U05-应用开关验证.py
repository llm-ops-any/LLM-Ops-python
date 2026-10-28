#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""U-05 验证：应用级语音开关（FR-06 / AC-08）经 nginx 读写并保持"""
import os

import requests

BASE = "http://llmops-nginx/api"
HEADERS = {"Authorization": f"Bearer {os.environ['TOKEN']}"}

from app.http.app import app as flask_app  # noqa: E402
from app.http.module import injector  # noqa: E402
from internal.model import App, Message  # noqa: E402
from pkg.sqlalchemy import SQLAlchemy  # noqa: E402


def get_app_id():
    with flask_app.app_context():
        db = injector.get(SQLAlchemy)
        message = (
            db.session.query(Message)
            .filter(Message.answer != "")
            .order_by(Message.created_at.desc())
            .first()
        )
        return str(message.app_id)


def main():
    app_id = get_app_id()
    print(f"app_id = {app_id}")

    print("=== 打开两个语音开关 ===")
    resp = requests.post(
        f"{BASE}/apps/{app_id}/draft-app-config",
        headers=HEADERS,
        json={
            "speech_to_text": {"enable": True},
            "text_to_speech": {"enable": True, "voice": "echo", "auto_play": False},
        },
        timeout=30,
    )
    print(f"  POST HTTP {resp.status_code} code={resp.json().get('code')}")

    print("=== 重新读取草稿配置（验证落库保持）===")
    resp = requests.get(f"{BASE}/apps/{app_id}/draft-app-config", headers=HEADERS, timeout=30)
    data = resp.json().get("data") or {}
    print(f"  GET HTTP {resp.status_code}")
    print(f"  speech_to_text   = {data.get('speech_to_text')}")
    print(f"  text_to_speech   = {data.get('text_to_speech')}")

    speech_ok = bool((data.get("speech_to_text") or {}).get("enable"))
    tts_ok = bool((data.get("text_to_speech") or {}).get("enable"))
    print(f"  AC-08 结论：语音转文本保持={speech_ok}  文本转语音保持={tts_ok}")

    print("=== 还原为关闭 ===")
    resp = requests.post(
        f"{BASE}/apps/{app_id}/draft-app-config",
        headers=HEADERS,
        json={
            "speech_to_text": {"enable": False},
            "text_to_speech": {"enable": False, "voice": "echo", "auto_play": False},
        },
        timeout=30,
    )
    print(f"  POST HTTP {resp.status_code} code={resp.json().get('code')}")


if __name__ == "__main__":
    main()
