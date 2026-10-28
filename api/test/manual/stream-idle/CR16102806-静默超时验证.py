#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CR-16102806 / AC-04 验证脚本：智能体静默超时

用法（容器内）：
    AGENT_SILENT_TIMEOUT=6 python /tmp/CR16102806-静默超时验证.py

预期：
    1. 先收到 1 条 agent_message（模拟"吐了一块内容"）
    2. 静默约 6 秒后收到 1 条 error，observation 含"未返回任何内容"
    3. 之后流结束（收到 None 后 break），总耗时约 6~10 秒
    4. error 只出现 1 次（guard 生效，不重复下发）
"""
import os
import sys
import time
import uuid

from app.http.app import app
from app.http.module import injector
from internal.core.agent.agents.agent_queue_manager import (
    AgentQueueManager,
    _get_silent_timeout,
)
from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom
from pkg.sqlalchemy import SQLAlchemy

with app.app_context():
    # 0.打印本次生效阈值，确认配置链路通
    silent_timeout = _get_silent_timeout()
    print(f"[config] AGENT_SILENT_TIMEOUT 生效值 = {silent_timeout} 秒")
    if silent_timeout <= 0:
        print("[FAIL] 阈值为 0，静默保护已关闭，无法验证 AC-04")
        sys.exit(1)

    db = injector.get(SQLAlchemy)
    manager = AgentQueueManager(user_id=uuid.uuid4(), invoke_from=InvokeFrom.DEBUGGER)
    task_id = uuid.uuid4()

    # 1.先吐一条内容，把 last_activity_time 置为当前
    manager.publish(task_id, AgentThought(
        id=uuid.uuid4(),
        task_id=task_id,
        event=QueueEvent.AGENT_MESSAGE,
        thought="第一块内容",
        answer="第一块内容",
        latency=0.1,
    ))

    # 2.从此不再 publish 任何内容，等待静默超时
    start = time.time()
    error_count = 0
    events = []
    for item in manager.listen(task_id):
        elapsed = time.time() - start
        events.append(item.event)
        print(f"[+{elapsed:5.1f}s] event = {item.event}"
              + (f" | observation = {getattr(item, 'observation', '')}" if item.event == QueueEvent.ERROR else ""))
        if item.event == QueueEvent.ERROR:
            error_count += 1

    total = time.time() - start
    print(f"\n[结果] 总耗时 {total:.1f}s，事件序列 = {events}")

    ok = True
    if error_count != 1:
        print(f"[FAIL] error 事件应只出现 1 次，实际 {error_count} 次")
        ok = False
    if total < silent_timeout:
        print(f"[FAIL] 结束过早（{total:.1f}s < 阈值 {silent_timeout}s）")
        ok = False
    if total > silent_timeout + 5:
        print(f"[FAIL] 结束过晚（{total:.1f}s，超出阈值+5s）")
        ok = False

    print("[PASS] AC-04 通过：静默超时能终止并给出可读原因" if ok else "[FAIL] AC-04 未通过")
    sys.exit(0 if ok else 1)
