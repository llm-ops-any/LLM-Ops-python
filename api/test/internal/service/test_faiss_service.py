#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : test_faiss_service.py
@Desc    : FAISS 检索服务单元测试（CR-16102600）

背景：2026-10-26 交付后出现 `AttributeError: can't set attribute 'embeddings'`，
原因是给 `FAISS.embeddings`（只读 property）赋值。这里用两个用例锁死：
1. 该属性确实只读（防止以后又写 `faiss.embeddings = ...`）；
2. `convert_faiss_to_tool` 必须通过底层字段 `_embeddings` 同步最新向量化实例。
"""
from unittest.mock import MagicMock

import pytest
from langchain_community.vectorstores.faiss import FAISS

from internal.service.faiss_service import FaissService


class TestFaissEmbeddingsSync:
    """向量化实例同步"""

    def test_faiss_embeddings_property_is_readonly(self):
        """FAISS.embeddings 是只读 property：直接赋值必抛 AttributeError"""
        faiss = FAISS.__new__(FAISS)

        with pytest.raises(AttributeError):
            faiss.embeddings = MagicMock()

    def test_convert_faiss_to_tool_syncs_latest_embeddings(self, monkeypatch):
        """转工具时把最新向量化实例写入底层字段，且不抛异常"""
        fake_faiss = MagicMock()
        monkeypatch.setattr(
            "internal.service.faiss_service.FAISS.load_local",
            lambda **kwargs: fake_faiss,  # noqa: ARG005
        )

        latest_embeddings = MagicMock()
        embeddings_service = MagicMock()
        embeddings_service.embeddings = latest_embeddings

        service = FaissService(embeddings_service=embeddings_service)
        tool = service.convert_faiss_to_tool()

        assert service.faiss is fake_faiss
        assert fake_faiss._embeddings is latest_embeddings
        assert tool is not None
