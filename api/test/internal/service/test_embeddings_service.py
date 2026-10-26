#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : test_embeddings_service.py
@Desc    : 向量化服务单元测试（CR-16102600）

锁死三件容易改错的事：
1. 必须显式传 `check_embedding_ctx_length=False`（否则中转平台 400）；
2. `dimensions` 必须跟随 `EMBEDDINGS_DIMENSIONS`（预置 FAISS 索引写死 1536）；
3. 缓存命名空间必须带模型与维度，避免换模型后复用旧向量。

全部使用替身，不联网、不读真实凭证。
"""
from unittest.mock import MagicMock

import pytest

from internal.service import embeddings_service as module
from internal.service.embeddings_service import DEFAULT_EMBEDDINGS_MODEL, EmbeddingsService
from internal.service.model_provider_service import ProviderConfig


@pytest.fixture
def captured(monkeypatch, app):
    """替换 OpenAIEmbeddings / RedisStore / CacheBackedEmbeddings，并记录入参"""
    record = {"embeddings_kwargs": [], "namespace": []}

    class _FakeOpenAIEmbeddings:
        def __init__(self, **kwargs):
            record["embeddings_kwargs"].append(kwargs)
            self.kwargs = kwargs

    def _fake_from_bytes_store(embedding, store, namespace=None):  # noqa: ARG001
        record["namespace"].append(namespace)
        return MagicMock(namespace=namespace)

    monkeypatch.setattr(module, "OpenAIEmbeddings", _FakeOpenAIEmbeddings)
    monkeypatch.setattr(module, "RedisStore", MagicMock())
    monkeypatch.setattr(module.CacheBackedEmbeddings, "from_bytes_store", staticmethod(_fake_from_bytes_store))
    monkeypatch.setattr(
        "internal.service.model_provider_service.get_active_config",
        lambda force_refresh=False: ProviderConfig(  # noqa: ARG005
            base_url="https://cfg.example.com/v1",
            api_key="sk-test-config-key",
            source="database",
        ),
    )
    return record


@pytest.fixture
def service(app, captured, monkeypatch):
    """在应用上下文内构造向量化服务"""
    monkeypatch.setenv("EMBEDDINGS_MODEL", "text-embedding-v4")
    monkeypatch.setenv("EMBEDDINGS_DIMENSIONS", "1536")
    with app.app_context():
        yield EmbeddingsService(redis=MagicMock())


class TestBuildEmbeddings:
    """构建向量化实例时的参数"""

    def test_passes_check_embedding_ctx_length_false(self, service, captured):
        """必须关闭 tiktoken 分词，否则中转平台报 contents is neither str nor list of str"""
        kwargs = captured["embeddings_kwargs"][0]

        assert kwargs["check_embedding_ctx_length"] is False

    def test_uses_model_and_dimensions_from_env(self, service, captured):
        """模型与维度来自环境变量，维度转成 int"""
        kwargs = captured["embeddings_kwargs"][0]

        assert kwargs["model"] == "text-embedding-v4"
        assert kwargs["dimensions"] == 1536

    def test_injects_base_url_and_key_from_config(self, service, captured):
        """接口地址与密钥跟随大模型设置（未配置时才回退环境变量）"""
        kwargs = captured["embeddings_kwargs"][0]

        assert kwargs["openai_api_base"] == "https://cfg.example.com/v1"
        assert kwargs["openai_api_key"] == "sk-test-config-key"

    def test_cache_namespace_contains_model_and_dimensions(self, service, captured):
        """缓存命名空间带模型与维度，换模型后不复用旧向量"""
        assert captured["namespace"][0] == "embeddings:text-embedding-v4:1536"

    def test_default_model_constant(self):
        """默认模型是实测可用的 text-embedding-v4"""
        assert DEFAULT_EMBEDDINGS_MODEL == "text-embedding-v4"


class TestEnsureFresh:
    """配置变更后的自动重建"""

    def test_rebuild_when_model_changes(self, service, captured, monkeypatch):
        """EMBEDDINGS_MODEL 变化后访问 embeddings 会重建实例"""
        assert len(captured["embeddings_kwargs"]) == 1

        monkeypatch.setenv("EMBEDDINGS_MODEL", "text-embedding-v3")
        monkeypatch.setenv("EMBEDDINGS_DIMENSIONS", "1024")
        _ = service.embeddings

        assert len(captured["embeddings_kwargs"]) == 2
        assert captured["embeddings_kwargs"][1]["dimensions"] == 1024
        assert captured["namespace"][1] == "embeddings:text-embedding-v3:1024"

    def test_keeps_old_instance_when_signature_fails(self, service, captured, monkeypatch):
        """读取凭证抛异常时保留现有实例，不影响正在进行中的请求"""

        def _boom(cls):
            raise RuntimeError("config unavailable")

        monkeypatch.setattr(EmbeddingsService, "_current_signature", classmethod(_boom))

        assert service.embeddings is not None
        assert len(captured["embeddings_kwargs"]) == 1


class TestTokenCount:
    """token 计数"""

    def test_calculate_token_count(self):
        """中文文本的 token 数应大于 0"""
        assert EmbeddingsService.calculate_token_count("你好，世界") > 0
