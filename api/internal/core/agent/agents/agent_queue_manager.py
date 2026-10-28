#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/10/24 13:45
@Author  : thezehui@gmail.com
@File    : agent_queue_manager.py
"""
import os
import queue
import time
import uuid
from queue import Queue
from typing import Generator
from uuid import UUID

from redis import Redis

from internal.core.agent.entities.queue_entity import AgentThought, QueueEvent
from internal.entity.conversation_entity import InvokeFrom

# CR-16102806 / FIX-3：默认静默超时（秒）。
# 语义与"总超时"不同——总超时管任务太大，静默超时管链路已死。
# 实测正常长输出的最长静默约 105 秒，故取 300 秒作阈值，留约 3 倍余量。
DEFAULT_SILENT_TIMEOUT = 300


def _get_silent_timeout() -> int:
    """读取静默超时配置，请求上下文可用时优先取 Flask 配置，否则回落环境变量"""
    try:
        from flask import current_app

        return int(current_app.config.get("AGENT_SILENT_TIMEOUT", DEFAULT_SILENT_TIMEOUT))
    except Exception:
        return int(os.getenv("AGENT_SILENT_TIMEOUT", DEFAULT_SILENT_TIMEOUT))


class AgentQueueManager:
    """智能体队列管理器"""
    user_id: UUID
    invoke_from: InvokeFrom
    redis_client: Redis
    _queues: dict[str, Queue]

    def __init__(
            self,
            user_id: UUID,
            invoke_from: InvokeFrom,
    ) -> None:
        """构造函数，初始化智能体队列管理器"""
        # 1.初始化数据
        self.user_id = user_id
        self.invoke_from = invoke_from
        self._queues = {}

        # 2.内部初始化redis_client
        from app.http.module import injector
        self.redis_client = injector.get(Redis)

    def listen(self, task_id: UUID) -> Generator:
        """监听队列返回的生成式数据"""
        # 1.定义基础数据记录超时时间、开始时间、最后一次ping通时间
        listen_timeout = 600
        # CR-16102806 / FIX-3：静默超时，与总超时并存
        silent_timeout = _get_silent_timeout()
        start_time = time.time()
        last_ping_time = 0
        # 最后一次收到"非 ping"事件的时间——ping 只证明连接活着，不证明模型在输出
        last_activity_time = start_time
        silent_triggered = False

        # 2.创建循环队列执行死循环读取数据，直到超时或者数据读取完毕
        while True:
            try:
                # 3.从队列中提取数据并检测数据是否存在，如果存在则使用yield关键字返回
                item = self.queue(task_id).get(timeout=1)
                if item is None:
                    break
                # CR-16102806：只有内容类事件才刷新"活动时间"，ping 不算
                if getattr(item, "event", None) != QueueEvent.PING:
                    last_activity_time = time.time()
                yield item
            except queue.Empty:
                continue
            finally:
                # 4.计算获取数据的总耗时
                elapsed_time = time.time() - start_time
                idle_time = time.time() - last_activity_time

                # 5.每10秒发起一个ping请求
                if elapsed_time // 10 > last_ping_time:
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(),
                        task_id=task_id,
                        event=QueueEvent.PING,
                    ))
                    last_ping_time = elapsed_time // 10

                # 6.CR-16102806：静默超时判定（先于总超时），命中后给出可读原因
                #   说明：guard 必须有——publish 会把 None 塞进队列，下一轮 break 时
                #        finally 仍会执行，不 guard 会重复下发 ERROR
                if not silent_triggered and silent_timeout > 0 and idle_time >= silent_timeout:
                    silent_triggered = True
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(),
                        task_id=task_id,
                        event=QueueEvent.ERROR,
                        observation=(
                            f"模型已连续 {silent_timeout} 秒未返回任何内容，"
                            f"判定上游链路中断，请重试或缩短提问内容"
                        ),
                    ))
                # 7.判断总耗时是否超时，如果超时则往队列中添加超时事件
                elif elapsed_time >= listen_timeout:
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(),
                        task_id=task_id,
                        event=QueueEvent.TIMEOUT,
                    ))

                # 7.检测是否停止，如果已经停止则添加停止事件
                if self._is_stopped(task_id):
                    self.publish(task_id, AgentThought(
                        id=uuid.uuid4(),
                        task_id=task_id,
                        event=QueueEvent.STOP,
                    ))

    def stop_listen(self, task_id: UUID) -> None:
        """停止监听队列信息"""
        self.queue(task_id).put(None)

    def publish(self, task_id: UUID, agent_thought: AgentThought) -> None:
        """发布事件信息到队列"""
        # 1.将事件添加到队列中
        self.queue(task_id).put(agent_thought)

        # 2.检测事件类型是否为需要停止的类型，涵盖STOP、ERROR、TIMEOUT、AGENT_END
        if agent_thought.event in [QueueEvent.STOP, QueueEvent.ERROR, QueueEvent.TIMEOUT, QueueEvent.AGENT_END]:
            self.stop_listen(task_id)

    def publish_error(self, task_id: UUID, error) -> None:
        """发布错误信息到队列"""
        self.publish(task_id, AgentThought(
            id=uuid.uuid4(),
            task_id=task_id,
            event=QueueEvent.ERROR,
            observation=str(error),
        ))

    def _is_stopped(self, task_id: UUID) -> bool:
        """检测任务是否停止"""
        task_stopped_cache_key = self.generate_task_stopped_cache_key(task_id)
        result = self.redis_client.get(task_stopped_cache_key)

        if result is not None:
            return True
        return False

    def queue(self, task_id: UUID) -> Queue:
        """根据传递的task_id获取对应的任务队列信息"""
        # 1.从队列字典中获取对应的任务队列
        q = self._queues.get(str(task_id))

        # 2.检测队列是否存在，如果不存在则创建队列，并添加缓存键标识
        if not q:
            # 3.添加缓存键标识
            user_prefix = "account" if self.invoke_from in [
                InvokeFrom.WEB_APP, InvokeFrom.DEBUGGER, InvokeFrom.ASSISTANT_AGENT,
            ] else "end-user"

            # 4.设置任务对应的缓存键，代表这次任务已经开始了
            self.redis_client.setex(
                self.generate_task_belong_cache_key(task_id),
                1800,
                f"{user_prefix}-{str(self.user_id)}",
            )

            # 5.将任务队列添加到队列字典中
            q = Queue()
            self._queues[str(task_id)] = q

        return q

    @classmethod
    def set_stop_flag(cls, task_id: UUID, invoke_from: InvokeFrom, user_id: UUID) -> None:
        """根据传递的任务id+调用来源停止某次会话"""
        # 1.获取redis_client客户端
        from app.http.module import injector
        redis_client = injector.get(Redis)

        # 2.获取当前任务的缓存键，如果任务没执行，则不需要停止
        result = redis_client.get(cls.generate_task_belong_cache_key(task_id))
        if not result:
            return

        # 3.计算对应缓存键的结果
        user_prefix = "account" if invoke_from in [
            InvokeFrom.WEB_APP, InvokeFrom.DEBUGGER, InvokeFrom.ASSISTANT_AGENT,
        ] else "end-user"
        if result.decode("utf-8") != f"{user_prefix}-{str(user_id)}":
            return

        # 4.生成停止键标识
        stopped_cache_key = cls.generate_task_stopped_cache_key(task_id)
        redis_client.setex(stopped_cache_key, 600, 1)

    @classmethod
    def generate_task_belong_cache_key(cls, task_id: UUID) -> str:
        """生成任务专属的缓存键"""
        return f"generate_task_belong:{str(task_id)}"

    @classmethod
    def generate_task_stopped_cache_key(cls, task_id: UUID) -> str:
        """生成任务已停止的缓存键"""
        return f"generate_task_stopped:{str(task_id)}"
