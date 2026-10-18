#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/12/02 15:30
@Author  : thezehui@gmail.com
@File    : language_model_service.py
"""
import logging
import mimetypes
import os
from dataclasses import dataclass
from typing import Any

from flask import current_app
from injector import inject

from internal.core.language_model import LanguageModelManager
from internal.core.language_model.entities.model_entity import BaseLanguageModel
from internal.exception import NotFoundException
from internal.lib.helper import convert_model_to_dict
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService


@inject
@dataclass
class LanguageModelService(BaseService):
    """语言模型服务"""
    db: SQLAlchemy
    language_model_manager: LanguageModelManager

    def get_language_models(self) -> list[dict[str, Any]]:
        """获取LLMOps项目中的所有模型列表信息"""
        # 1.调用语言模型管理器获取提供商列表
        providers = self.language_model_manager.get_providers()

        # 2.构建语言模型列表，循环读取数据
        language_models = []
        for provider in providers:
            # 3.获取提供商实体和模型实体列表
            provider_entity = provider.provider_entity
            model_entities = provider.get_model_entities()

            # 4.构建响应字典结构
            language_model = {
                "name": provider_entity.name,
                "position": provider.position,
                "label": provider_entity.label,
                "icon": provider_entity.icon,
                "description": provider_entity.description,
                "background": provider_entity.background,
                "support_model_types": provider_entity.supported_model_types,
                "models": convert_model_to_dict(model_entities),
            }
            language_models.append(language_model)

        return language_models

    def get_language_model(self, provider_name: str, model_name: str) -> dict[str, Any]:
        """根据传递的提供者名字+模型名字获取模型详细信息"""
        # 1.获取提供者+模型实体信息
        provider = self.language_model_manager.get_provider(provider_name)
        if not provider:
            raise NotFoundException("该服务提供者不存在")

        # 2.获取模型实体
        model_entity = provider.get_model_entity(model_name)
        if not model_entity:
            raise NotFoundException("该模型不存在")

        return convert_model_to_dict(model_entity)

    def get_language_model_icon(self, provider_name: str) -> tuple[bytes, str]:
        """根据传递的提供者名字获取提供商对应的图标信息"""
        # 1.获取提供者信息
        provider = self.language_model_manager.get_provider(provider_name)
        if not provider:
            raise NotFoundException("该服务提供者不存在")

        # 2.获取项目的根路径信息
        root_path = os.path.dirname(os.path.dirname(current_app.root_path))

        # 3.拼接得到提供者所在的文件夹
        provider_path = os.path.join(
            root_path,
            "internal", "core", "language_model", "providers", provider_name,
        )

        # 4.拼接得到icon对应的路径
        icon_path = os.path.join(provider_path, "_asset", provider.provider_entity.icon)

        # 5.检测icon是否存在
        if not os.path.exists(icon_path):
            raise NotFoundException(f"该模型提供者_asset下未提供图标")

        # 6.读取icon的类型
        mimetype, _ = mimetypes.guess_type(icon_path)
        mimetype = mimetype or "application/octet-stream"

        # 7.读取icon的字节数据
        with open(icon_path, "rb") as f:
            byte_data = f.read()
            return byte_data, mimetype

    def load_language_model(self, model_config: dict[str, Any]) -> BaseLanguageModel:
        """根据传递的模型配置加载大语言模型，并返回其实例"""
        try:
            # 1.从model_config中提取出provider、model、parameters
            provider_name = model_config.get("provider", "")
            model_name = model_config.get("model", "")
            parameters = model_config.get("parameters", {})

            # 2.从模型管理器获取提供者、模型实体、模型类
            provider = self.language_model_manager.get_provider(provider_name)
            model_entity = provider.get_model_entity(model_name)
            model_class = provider.get_model_class(model_entity.model_type)

            # 3.实例化模型后并返回
            # 说明：把平台(provider)与模型名一并写入metadata，供智能体流式适配层按平台/模型
            #      选择适配器；也可在模型配置metadata里设置stream_adapter强制指定适配器。
            return model_class(
                **model_entity.attributes,
                **parameters,
                features=model_entity.features,
                metadata={
                    **model_entity.metadata,
                    "provider": provider_name,
                    "model": model_name,
                },
            )
        except Exception as e:
            # 说明：兜底前必须把真实异常打出来。此处原先是一个静默的except，
            # 模型配置写错(如选了平台上不存在的模型)时会被悄悄替换成兜底模型，
            # 前端最终只看到兜底模型报的model_not_found，真实原因被彻底掩盖。
            logging.exception(
                "加载大语言模型失败, 已降级为默认模型, 模型配置: %(config)s, 错误信息: %(error)s",
                {"config": model_config, "error": str(e)},
            )
            return self.load_default_language_model()

    def load_default_language_model(self) -> BaseLanguageModel:
        """加载默认的大语言模型，在模型管理器中获取不到模型或者出错时使用默认模型进行兜底"""
        # 说明：不能硬编码ChatOpenAI(model="gpt-4o-mini")——本项目所有模型统一走uino中转平台
        # (由OPENAI_API_BASE注入)，该模型名在平台上并不存在，用它兜底只会把"配置错误"替换成
        # "model_not_found"，等于既没兜住底又多绕一层。故改为从模型管理器读取平台上真实存在的
        # 模型作为兜底，并允许通过环境变量覆盖(平台模型清单随时可能变动)。
        provider_name = os.environ.get("DEFAULT_LLM_PROVIDER") or "uino"
        model_name = os.environ.get("DEFAULT_LLM_MODEL") or "deepseek-v4-flash"

        provider = self.language_model_manager.get_provider(provider_name)
        model_entity = provider.get_model_entity(model_name)
        model_class = provider.get_model_class(model_entity.model_type)
        return model_class(
            **model_entity.attributes,
            features=model_entity.features,
            metadata={
                **model_entity.metadata,
                "provider": provider_name,
                "model": model_name,
            },
        )
