#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/8/30 13:35
@Author  : thezehui@gmail.com
@File    : embeddings_service.py
"""
import os
from dataclasses import dataclass
from typing import Optional

import tiktoken
from injector import inject
from langchain.embeddings import CacheBackedEmbeddings
from langchain_community.storage import RedisStore
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from redis import Redis

# 默认向量化模型，可通过 EMBEDDINGS_MODEL 环境变量覆盖
# 说明：text-embedding-v4 为线上实测可用且与预置 FAISS 索引(1536维)同向量空间的模型，
#      qwen3-embedding-8b / text-embedding-3-small 在中转平台均无可用渠道(503)。
DEFAULT_EMBEDDINGS_MODEL = "text-embedding-v4"


@inject
@dataclass
class EmbeddingsService:
    """文本嵌入模型服务"""
    _store: RedisStore
    _embeddings: Embeddings
    _cache_backed_embeddings: CacheBackedEmbeddings
    _signature: Optional[tuple] = None

    def __init__(self, redis: Redis):
        """构造函数，初始化文本嵌入模型客户端、存储器、缓存客户端"""
        self._store = RedisStore(client=redis)
        self._signature = None
        self._build_embeddings()

    @classmethod
    def _current_signature(cls) -> tuple:
        """计算当前凭证与模型参数指纹，用于判断是否需要重建向量化实例"""
        # 说明：延迟导入，避免 service 包内部循环导入
        from internal.service.model_provider_service import get_active_config

        config = get_active_config()
        return (
            os.environ.get("EMBEDDINGS_MODEL", DEFAULT_EMBEDDINGS_MODEL),
            config.base_url,
            config.api_key,
            os.environ.get("EMBEDDINGS_DIMENSIONS", ""),
        )

    def _build_embeddings(self) -> None:
        """按当前配置构建向量化实例与缓存包装

        说明：
        1. 接口地址与密钥跟随"设置-大模型设置"，未配置时回退环境变量；
        2. 向量化输出维度需与本地预置的 FAISS 索引保持一致，
           维度不一致时 FAISS 检索会抛 AssertionError，故保留环境变量覆盖能力；
        3. 本方法使用"重建"而非"整体进程重启"，从而实现保存配置后无需重启即可生效。
        """
        from internal.service.model_provider_service import get_active_config

        config = get_active_config()
        model = os.environ.get("EMBEDDINGS_MODEL", DEFAULT_EMBEDDINGS_MODEL)
        dimensions = os.environ.get("EMBEDDINGS_DIMENSIONS", "")
        embeddings_kwargs = {}
        if config.base_url:
            embeddings_kwargs["openai_api_base"] = config.base_url
        if config.api_key:
            embeddings_kwargs["openai_api_key"] = config.api_key
        if dimensions:
            embeddings_kwargs["dimensions"] = int(dimensions)
        # 说明：中转平台不接受 tiktoken 分词后的整数数组，必须直接传原始字符串，
        #      否则接口返回 "contents is neither str nor list of str"。
        embeddings_kwargs["check_embedding_ctx_length"] = False

        self._embeddings = OpenAIEmbeddings(model=model, **embeddings_kwargs)
        # 说明：缓存命名空间带上模型与维度，避免换模型后复用旧向量导致检索结果错乱。
        self._cache_backed_embeddings = CacheBackedEmbeddings.from_bytes_store(
            self._embeddings,
            self._store,
            namespace=f"embeddings:{model}:{dimensions or 'default'}",
        )
        self._signature = self._current_signature()

    def _ensure_fresh(self) -> None:
        """校验凭证是否变化，变化时重建向量化实例(配置保存后无需重启)"""
        try:
            signature = self._current_signature()
        except Exception:
            # 说明：凭证读取异常时保留现有实例，不让知识库链路直接失败
            return
        if signature != self._signature:
            try:
                self._build_embeddings()
            except Exception:
                # 说明：重建失败(如地址不可达)时继续使用旧实例，避免影响正在进行的请求
                pass

    @classmethod
    def calculate_token_count(cls, query: str) -> int:
        """计算传入文本的token数"""
        encoding = tiktoken.encoding_for_model("gpt-3.5")
        return len(encoding.encode(query))

    @property
    def store(self) -> RedisStore:
        self._ensure_fresh()
        return self._store

    @property
    def embeddings(self) -> Embeddings:
        self._ensure_fresh()
        return self._embeddings

    @property
    def cache_backed_embeddings(self) -> CacheBackedEmbeddings:
        self._ensure_fresh()
        return self._cache_backed_embeddings
