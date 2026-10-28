#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CR-16102807 诊断：定位 _thread_chat 静默失败原因

用法（容器内）：
    python /tmp/wechat_thread_diag.py <message_id> <conversation_id>
"""
import sys
import traceback
from uuid import UUID

from app.http.app import app
from app.http.module import injector
from internal.model import App, Message
from internal.service import WechatService, AppConfigService
from pkg.sqlalchemy import SQLAlchemy

MESSAGE_ID = UUID("20ee893b-f4cb-4123-8efc-393f6e64a802")
CONVERSATION_ID = UUID("16d3f9f9-66ac-4cc6-8a56-b5d31e2ec263")
APP_ID = UUID("3e9d86fd-a565-4578-a364-3d2706e2da86")

with app.app_context():
    db = injector.get(SQLAlchemy)
    svc = injector.get(WechatService)
    cfg_svc = injector.get(AppConfigService)

    a = db.session.query(App).filter(App.id == APP_ID).one()
    m = db.session.query(Message).filter(Message.id == MESSAGE_ID).one()
    print(f"[1] app={a.name} status={a.status} query={m.query!r}")

    try:
        # get_app_config 内部要拼工具图标 URL，依赖 request context，
        # 真实链路里它是在主线程（有请求上下文）调用的，这里用测试上下文模拟
        with app.test_request_context('/api/wechat/' + str(APP_ID)):
            cfg = cfg_svc.get_app_config(a)
        print(f"[2] app_config 取到，model={cfg.get('model_config', {}).get('model')} tools={len(cfg.get('tools') or [])}")
    except Exception:
        print("[2] get_app_config 失败：")
        traceback.print_exc()
        sys.exit(1)

    try:
        svc._thread_chat(
            flask_app=app,
            app_id=APP_ID,
            app_config=cfg,
            conversation_id=CONVERSATION_ID,
            message_id=MESSAGE_ID,
            query=m.query,
        )
        print("[3] _thread_chat 正常结束")
    except Exception:
        print("[3] _thread_chat 抛异常：")
        traceback.print_exc()
        sys.exit(1)
