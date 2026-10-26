#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : model_provider_schema.py
@Desc    : 大模型服务设置相关的请求与响应结构
"""
from flask_wtf import FlaskForm
from marshmallow import Schema, fields
from wtforms import StringField
from wtforms.validators import DataRequired, Length, Optional, Regexp


class GetModelProviderResp(Schema):
    """大模型服务设置响应结构，不含任何密钥明文"""
    base_url = fields.String(dump_default="")
    has_api_key = fields.Boolean(dump_default=False)
    masked_api_key = fields.String(dump_default="")
    source = fields.String(dump_default="")
    source_label = fields.String(dump_default="")


class UpdateModelProviderReq(FlaskForm):
    """更新大模型服务设置请求结构"""
    base_url = StringField(
        "base_url",
        default="",
        validators=[
            DataRequired("API地址不能为空"),
            Regexp(r"^https?://\S+$", message="API地址必须以http://或https://开头"),
            Length(max=512, message="API地址长度不能超过512个字符"),
        ],
    )
    api_key = StringField(
        "api_key",
        default="",
        validators=[
            Optional(),
            Length(max=512, message="API Key长度不能超过512个字符"),
        ],
    )


class TestModelProviderConnectionReq(FlaskForm):
    """测试大模型服务连通性请求结构，两个字段均可为空(为空则使用已保存配置)"""
    base_url = StringField(
        "base_url",
        default="",
        validators=[
            Optional(),
            Length(max=512, message="API地址长度不能超过512个字符"),
        ],
    )
    api_key = StringField(
        "api_key",
        default="",
        validators=[
            Optional(),
            Length(max=512, message="API Key长度不能超过512个字符"),
        ],
    )
