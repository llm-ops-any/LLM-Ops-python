#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CR-16102807 诊断 2：在线程里跑 _thread_chat，捕获异常

用法（容器内）：
    python /tmp/wechat_thread_diag2.py
"""
import threading
import traceback
from uuid import UUID

from app.http.app import app
from app.http.module import injector
from internal.model import App, Message
from internal.service import WechatService, AppConfigService
from pkg.sqlalchemy import SQLAlchemy

APP_ID = UUID("3e9d86fd-a565-4578-a364-3d2706e2da86")
MESSAGE_ID = UUID("15756d7b-9d65-4384-8919-9e3264d9516b")
CONVERSATION_ID = UUID("482e66f7-5a04-4600-a49b-2636d0bfc572")

captured = {}


def worker(svc, cfg, flask_app, query):
    """与真实链路一致的入口"""
    try:
        svc._thread_chat(
            flask_app=flask_app,
            app_id=APP_ID,
            app_config=cfg,
            conversation_id=CONVERSATION_ID,
            message_id=MESSAGE_ID,
            query=query,
        )
        captured["ok"] = True
    except Exception as e:
        captured["error"] = e
        captured["trace"] = traceback.format_exc()


with app.app_context():
    db = injector.get(SQLAlchemy)
    svc = injector.get(WechatService)
    cfg_svc = injector.get(AppConfigService)
    a = db.session.query(App).filter(App.id == APP_ID).one()
    m = db.session.query(Message).filter(Message.id == MESSAGE_ID).one()

    # 真实链路是在请求上下文里取 app_config 的，这里模拟
    with app.test_request_context("/api/wechat/" + str(APP_ID)):
        cfg = cfg_svc.get_app_config(a)

    print(f"[1] app={a.name} status={a.status} tools={len(cfg.get('tools') or [])}")
    print(f"[2] 起线程，flask_app 类型 = {type(app)}")

    t = threading.Thread(
        target=worker,
        args=(svc, cfg, app, m.query),
        name="diag-wechat",
    )
    # 与真实链路一致：默认 daemon=False
    t.start()
    t.join(timeout=120)

    print(f"[3] 线程存活 = {t.is_alive()}")
    if captured.get("ok"):
        print("[3] 线程内执行成功")
    elif captured.get("error") is not None:
        print("[3] 线程内抛异常：")
        print(captured["trace"])
    else:
        print("[3] 线程 120 秒内未结束，未见异常")
