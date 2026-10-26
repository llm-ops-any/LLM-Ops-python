#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : model_provider_handler.py
@Desc    : 大模型服务设置的控制器，提供读取、保存与连通性测试三个接口
"""
from dataclasses import dataclass

from flask_login import login_required
from injector import inject

from internal.schema.model_provider_schema import (
    GetModelProviderResp,
    TestModelProviderConnectionReq,
    UpdateModelProviderReq,
)
from internal.service import ModelProviderService
from pkg.response import success_json, validate_error_json


@inject
@dataclass
class ModelProviderHandler:
    """大模型服务设置处理器"""
    model_provider_service: ModelProviderService

    @login_required
    def get_model_provider(self):
        """读取当前大模型服务设置(密钥仅返回固定掩码)"""
        resp = GetModelProviderResp()
        return success_json(resp.dump(self.model_provider_service.get_masked_setting()))

    @login_required
    def update_model_provider(self):
        """保存大模型服务设置，api_key为空表示只修改地址"""
        req = UpdateModelProviderReq()
        if not req.validate():
            return validate_error_json(req.errors)

        self.model_provider_service.save_config(req.base_url.data, req.api_key.data)
        resp = GetModelProviderResp()
        return success_json(resp.dump(self.model_provider_service.get_masked_setting()))

    @login_required
    def test_model_provider_connection(self):
        """测试大模型服务连通性，不落库"""
        req = TestModelProviderConnectionReq()
        if not req.validate():
            return validate_error_json(req.errors)

        return success_json(
            self.model_provider_service.test_connection(req.base_url.data, req.api_key.data)
        )
