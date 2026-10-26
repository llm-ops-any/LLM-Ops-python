#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/12/03 13:48
@Author  : thezehui@gmail.com
@File    : faiss_service.py
"""
import os

from injector import inject
from langchain_community.vectorstores import FAISS
from langchain_core.pydantic_v1 import BaseModel, Field
from langchain_core.tools import BaseTool, tool

from internal.core.agent.entities.agent_entity import DATASET_RETRIEVAL_TOOL_NAME
from internal.lib.helper import combine_documents
from .embeddings_service import EmbeddingsService


@inject
class FaissService:
    """Faiss向量数据库服务"""
    faiss: FAISS
    embeddings_service: EmbeddingsService

    def __init__(self, embeddings_service: EmbeddingsService):
        """构造函数，完成Faiss向量数据库的初始化"""
        # 1.赋值embeddings_service
        self.embeddings_service = embeddings_service

        # 2.获取internal路径并计算本地向量数据库的实际路径
        internal_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        faiss_vector_store_path = os.path.join(internal_path, "core", "vector_store")

        # 3.初始化faiss向量数据库
        self.faiss = FAISS.load_local(
            folder_path=faiss_vector_store_path,
            embeddings=self.embeddings_service.embeddings,
            allow_dangerous_deserialization=True,
        )

    def convert_faiss_to_tool(self) -> BaseTool:
        """将Faiss向量数据库检索器转换成LangChain工具"""
        # 0.同步最新的向量化实例：设置页改了API地址/Key后，本服务缓存的旧实例会继续用旧凭证
        #   说明：FAISS 在查询时才调用 embeddings，此处赋值即可让检索跟随最新配置
        #   坑：FAISS.embeddings 是只读 property（返回 self._embeddings，无 setter），
        #       直接 `faiss.embeddings = x` 会抛 AttributeError: can't set attribute，必须写底层字段
        self.faiss._embeddings = self.embeddings_service.embeddings

        # 1.将Faiss向量数据库转换成检索器
        retrieval = self.faiss.as_retriever(
            search_type="mmr",
            search_kwargs={"k": 5, "fetch_k": 20},
        )

        # 2.构建检索链，并将检索的结果合并成字符串
        search_chain = retrieval | combine_documents

        class DatasetRetrievalInput(BaseModel):
            """知识库检索工具输入结构"""
            query: str = Field(description="知识库检索query语句，类型为字符串")

        @tool(DATASET_RETRIEVAL_TOOL_NAME, args_schema=DatasetRetrievalInput)
        def dataset_retrieval(query: str) -> str:
            """如果需要检索扩展的知识库内容，当你觉得用户的提问超过你的知识范围时，可以尝试调用该工具，输入为搜索query语句，返回数据为检索内容字符串"""
            return search_chain.invoke(query)

        return dataset_retrieval
