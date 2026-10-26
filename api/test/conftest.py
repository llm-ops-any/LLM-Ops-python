#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/4/4 16:39
@Author  : thezehui@gmail.com
@File    : conftest.py.py
"""
import os

import pytest
from sqlalchemy.orm import sessionmaker, scoped_session

from app.http.app import app as _app
from internal.extension.database_extension import db as _db

# 历史遗留的硬编码登录态，已于 2024-12 过期，仅作缺省回退值保留（不删，避免 diff 噪音）
_LEGACY_ACCESS_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiI0NmRiMzBkMS0zMTk5LTRlNzktYTBjZC1hYmYxMmZhNjg1OGYiLCJpc3MiOiJsbG1vcHMiLCJleHAiOjE3MzM1MDU2NTR9."
    "HSKjINY58fzengY3BmxIDOnJyACnBnz9NmgVN3y02iI"
)


@pytest.fixture
def app():
    """获取Flask应用并返回"""
    _app.config["TESTING"] = True
    return _app


@pytest.fixture
def client(app):
    """获取Flask应用的测试应用，并返回

    登录态 token 从环境变量 ``LLMOPS_TEST_TOKEN`` 读取，**不写进仓库**（凭证不入库）。
    历史硬编码的 token（exp=2024-12）已过期，不注入环境变量时相关用例会因
    ``UnauthorizedException`` 失败——这是如实暴露，不是用例本身有问题。

    运行方式（容器内）：:

        docker cp api/test llmops-api:/app/api/test
        docker exec -e PYTHONPATH=/app/api -w /app/api \
            -e LLMOPS_TEST_TOKEN=<当前有效 token> llmops-api python -m pytest test
    """
    with app.test_client() as client:
        access_token = os.getenv("LLMOPS_TEST_TOKEN", _LEGACY_ACCESS_TOKEN)
        client.environ_base["HTTP_AUTHORIZATION"] = f"Bearer {access_token}"
        yield client


@pytest.fixture
def db(app):
    """创建一个临时的数据库会话，当测试结束的时候回滚整个事务，从而实现测试与数据实际隔离

    注意：必须保存并**还原**原来的 ``_db.session``。否则用到本 fixture 的用例跑完后，
    后续用例拿到的是已被 ``remove()`` 的 scoped_session，表现为「单独跑通过、全量跑失败」的
    顺序相关污染（2026-10-26 全量回归时实测到，见测试记录）。
    """
    with app.app_context():
        # 0.保存原始会话，供 teardown 还原
        original_session = _db.session

        # 1.获取数据库连接并创建事务
        connection = _db.engine.connect()
        transaction = connection.begin()

        # 2.创建一个临时数据库会话
        session_factory = sessionmaker(bind=connection)
        session = scoped_session(session_factory)
        _db.session = session

        try:
            # 3.抛出数据库实例
            yield _db
        finally:
            # 4.回退数据库并关闭连接，随后清除会话并还原原始会话
            transaction.rollback()
            connection.close()
            session.remove()
            _db.session = original_session
