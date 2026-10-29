#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/8/4 10:25
@Author  : thezehui@gmail.com
@File    : api_provider_manager.py
"""
from dataclasses import dataclass
from typing import Type, Optional, Callable, Any
import json
import logging

import requests
from injector import inject
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, create_model, Field

from internal.core.tools.api_tools.entities import ToolEntity, ParameterTypeMap, ParameterIn

logger = logging.getLogger(__name__)

# 单次API工具请求的超时时间(秒)，避免上游无响应导致整个Agent请求被挂住
API_TOOL_REQUEST_TIMEOUT = 30
# 判断"结果为空"时，优先识别的列表字段名
EMPTY_RESULT_KEYS = ("value", "items", "results", "list", "records", "data")


@inject
@dataclass
class ApiProviderManager(BaseModel):
    """API工具提供者管理器，能根据传递的工具配置信息生成自定义LangChain工具"""

    @classmethod
    def _create_tool_func_from_tool_entity(cls, tool_entity: ToolEntity) -> Callable:
        """根据传递的信息创建发起API请求的函数"""

        def tool_func(**kwargs) -> str:
            """API工具请求函数"""
            # 1.定义变量存储来自path/query/header/cookie/request_body中的数据
            parameters = {
                ParameterIn.PATH: {},
                ParameterIn.HEADER: {},
                ParameterIn.QUERY: {},
                ParameterIn.COOKIE: {},
                ParameterIn.REQUEST_BODY: {}
            }

            # 2.更改参数结构映射
            parameter_map = {parameter.get("name"): parameter for parameter in tool_entity.parameters}
            header_map = {header.get("key"): header.get("value") for header in tool_entity.headers}

            # 3.循环遍历传递的所有字段并校验
            for key, value in kwargs.items():
                # 4.提取键值对关联的字段并校验
                parameter = parameter_map.get(key)
                if parameter is None:
                    continue

                # 5.将参数存储到合适的位置上，默认在query上
                parameters[parameter.get("in", ParameterIn.QUERY)][key] = value

            # 6.构建request请求并返回采集的内容
            response = requests.request(
                method=tool_entity.method,
                url=tool_entity.url.format(**parameters[ParameterIn.PATH]),
                params=parameters[ParameterIn.QUERY],
                json=parameters[ParameterIn.REQUEST_BODY],
                headers={**header_map, **parameters[ParameterIn.HEADER]},
                cookies=parameters[ParameterIn.COOKIE],
                timeout=API_TOOL_REQUEST_TIMEOUT,
            )

            # 7.状态码非2xx时返回明确的失败原因，避免模型把错误页面当作正常内容
            if not response.ok:
                return (
                    f"接口请求失败(HTTP {response.status_code}): "
                    f"{(response.text or '')[:1000]}"
                )

            # 8.响应体为空时给出明确提示，避免模型误以为拿到了内容
            text = response.text or ""
            if not text.strip():
                return "[平台提示] 接口调用成功(HTTP 200)，但响应体为空。请如实告知用户未获取到内容，不要编造。"

            # 9.结果列表为空时追加平台提示，帮助模型区分"没结果"和"调用失败"
            return cls._append_empty_result_notice(text)

        return tool_func

    @classmethod
    def _append_empty_result_notice(cls, text: str) -> str:
        """检测响应JSON中的结果列表是否为空，为空时在原文末尾追加平台提示"""
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return text

        try:
            if not cls._has_empty_result_list(data):
                return text
        except RecursionError:  # pragma: no cover - 极端深度的响应直接放行
            return text

        return (
            f"{text}\n"
            f"[平台提示] 接口调用成功，但结果列表为空(0 条)。"
            f"请如实告知用户未检索到内容，不要编造，并给出可执行的替代建议。"
        )

    @classmethod
    def _has_empty_result_list(cls, data: Any, depth: int = 0) -> bool:
        """递归检测响应结构中是否存在为空的结果列表(限制深度，避免遍历超大响应)"""
        if depth > 3:
            return False

        if isinstance(data, dict):
            for key, value in data.items():
                if key in EMPTY_RESULT_KEYS and isinstance(value, list) and len(value) == 0:
                    return True
                if isinstance(value, (dict, list)) and cls._has_empty_result_list(value, depth + 1):
                    return True
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)) and cls._has_empty_result_list(item, depth + 1):
                    return True

        return False

    @classmethod
    def _create_model_from_parameters(cls, parameters: list[dict]) -> Type[BaseModel]:
        """根据传递的parameters参数创建BaseModel子类"""
        fields = {}
        for parameter in parameters:
            field_name = parameter.get("name")
            field_type = ParameterTypeMap.get(parameter.get("type"), str)
            field_required = parameter.get("required", True)
            field_description = parameter.get("description", "")

            # 非必填参数必须显式给default=None，否则pydantic仍会把它当作必填，
            # 模型会被迫为每个可选参数编造一个值
            field_info = (
                Field(description=field_description)
                if field_required
                else Field(default=None, description=field_description)
            )
            fields[field_name] = (
                field_type if field_required else Optional[field_type],
                field_info,
            )

        return create_model("DynamicModel", **fields)

    def get_tool(self, tool_entity: ToolEntity) -> BaseTool:
        """根据传递的配置获取自定义API工具"""
        return StructuredTool.from_function(
            func=self._create_tool_func_from_tool_entity(tool_entity),
            name=f"{tool_entity.id}_{tool_entity.name}",
            description=tool_entity.description,
            args_schema=self._create_model_from_parameters(tool_entity.parameters),
        )
