#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/11/19 17:01
@Author  : thezehui@gmail.com
@File    : openapi_handler.py
"""
from dataclasses import dataclass
from uuid import UUID

from flask_login import login_required, current_user
from injector import inject

from internal.schema.openapi_schema import OpenAPIChatReq
from internal.service import OpenAPIService
from pkg.response import validate_error_json, compact_generate_response, success_message


@inject
@dataclass
class OpenAPIHandler:
    """开放API处理器"""
    openapi_service: OpenAPIService

    @login_required
    def chat(self):
        """开放Chat对话接口"""
        # 1.提取请求并校验数据
        req = OpenAPIChatReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务创建会话
        resp = self.openapi_service.chat(req, current_user)

        return compact_generate_response(resp)

    @login_required
    def stop_chat(self, task_id: UUID):
        """开放API停止对话接口"""
        # 1.调用服务停止指定的流式任务，鉴权由request_loader按蓝图分流完成（API Key → account）
        self.openapi_service.stop_chat(task_id, current_user)

        return success_message("停止开放API会话成功")
