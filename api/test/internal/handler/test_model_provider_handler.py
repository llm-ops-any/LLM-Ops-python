#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : test_model_provider_handler.py
@Desc    : 大模型设置三个接口的控制器测试（CR-16102600）

覆盖点：
1. 未登录访问必须被拒；
2. GET 只返回掩码，响应全文不含明文密钥；
3. POST 地址校验（空 / 非 http(s)）走校验错误分支；
4. POST 会把地址与 Key 原样传给服务层，api_key 允许留空；
5. 测试连接接口透传服务层结果。

说明：服务层方法全部被替身替换，用例不读写真实配置、不联网。
运行需要一个有效登录态，见 `conftest.py` 的 `LLMOPS_TEST_TOKEN` 说明。
"""
import json

import pytest

from internal.service import ModelProviderService
from pkg.response import HttpCode


@pytest.fixture
def masked_setting():
    """替身：页面展示用配置（只有掩码）"""
    return {
        "base_url": "https://cfg.example.com/v1",
        "has_api_key": True,
        "masked_api_key": "****",
        "source": "database",
        "source_label": "数据库配置",
    }


class TestAuth:
    """登录态要求"""

    def test_get_without_token_is_rejected(self, app):
        """未登录读取设置被拒"""
        with app.test_client() as unauthorized_client:
            resp = unauthorized_client.get("/model-provider")

        assert resp.json.get("code") == HttpCode.UNAUTHORIZED

    def test_update_without_token_is_rejected(self, app):
        """未登录保存设置被拒"""
        with app.test_client() as unauthorized_client:
            resp = unauthorized_client.post("/model-provider", json={"base_url": "https://a.com/v1"})

        assert resp.json.get("code") == HttpCode.UNAUTHORIZED


class TestGetModelProvider:
    """读取设置"""

    def test_returns_masked_key_only(self, client, masked_setting, monkeypatch):
        """只返回掩码，响应里没有 Key 明文"""
        monkeypatch.setattr(ModelProviderService, "get_masked_setting", lambda self: masked_setting)

        resp = client.get("/model-provider")
        body = json.dumps(resp.json, ensure_ascii=False)

        assert resp.json.get("code") == HttpCode.SUCCESS
        assert resp.json["data"]["masked_api_key"] == "****"
        assert resp.json["data"]["has_api_key"] is True
        assert "sk-" not in body


class TestUpdateModelProvider:
    """保存设置"""

    @pytest.mark.parametrize(
        "payload",
        [
            {},  # 缺地址
            {"base_url": ""},  # 空地址
            {"base_url": "ftp://a.com/v1"},  # 协议不合法
            {"base_url": "a.com/v1"},  # 缺协议
        ],
    )
    def test_invalid_base_url_rejected(self, client, payload):
        """地址非法时返回校验错误，不进入服务层"""
        resp = client.post("/model-provider", json=payload)

        assert resp.json.get("code") == HttpCode.VALIDATE_ERROR

    def test_base_url_too_long_rejected(self, client):
        """地址超过 512 字符被拒"""
        resp = client.post("/model-provider", json={"base_url": "https://a.com/" + "x" * 600})

        assert resp.json.get("code") == HttpCode.VALIDATE_ERROR

    def test_api_key_too_long_rejected(self, client):
        """Key 超过 512 字符被拒"""
        resp = client.post(
            "/model-provider",
            json={"base_url": "https://a.com/v1", "api_key": "sk-" + "x" * 600},
        )

        assert resp.json.get("code") == HttpCode.VALIDATE_ERROR

    def test_success_passes_params_to_service(self, client, masked_setting, monkeypatch):
        """保存成功：地址与 Key 原样传给服务层，返回值仍是掩码"""
        captured = {}

        def fake_save(self, base_url, api_key=None):  # noqa: ARG001
            captured["base_url"] = base_url
            captured["api_key"] = api_key

        monkeypatch.setattr(ModelProviderService, "save_config", fake_save)
        monkeypatch.setattr(ModelProviderService, "get_masked_setting", lambda self: masked_setting)

        resp = client.post(
            "/model-provider",
            json={"base_url": "https://a.com/v1", "api_key": "sk-test-input"},
        )

        assert resp.json.get("code") == HttpCode.SUCCESS
        assert captured == {"base_url": "https://a.com/v1", "api_key": "sk-test-input"}
        assert resp.json["data"]["masked_api_key"] == "****"
        assert "sk-test-input" not in json.dumps(resp.json, ensure_ascii=False)

    def test_empty_api_key_is_allowed(self, client, masked_setting, monkeypatch):
        """只改地址时 api_key 可以留空（服务层保留原密钥）"""
        captured = {}

        def fake_save(self, base_url, api_key=None):  # noqa: ARG001
            captured["base_url"] = base_url
            captured["api_key"] = api_key

        monkeypatch.setattr(ModelProviderService, "save_config", fake_save)
        monkeypatch.setattr(ModelProviderService, "get_masked_setting", lambda self: masked_setting)

        resp = client.post("/model-provider", json={"base_url": "https://a.com/v1"})

        assert resp.json.get("code") == HttpCode.SUCCESS
        assert captured["api_key"] in (None, "")


class TestTestConnection:
    """连通性测试接口"""

    def test_returns_service_result(self, client, monkeypatch):
        """把服务层探测结果原样返回"""
        monkeypatch.setattr(
            ModelProviderService,
            "test_connection",
            lambda self, base_url=None, api_key=None: {  # noqa: ARG005
                "ok": True,
                "status": 200,
                "message": "连接成功，共24个模型",
                "model_count": 24,
            },
        )

        resp = client.post("/model-provider/test-connection", json={})

        assert resp.json.get("code") == HttpCode.SUCCESS
        assert resp.json["data"]["ok"] is True
        assert resp.json["data"]["model_count"] == 24

    def test_invalid_scheme_rejected_by_schema(self, client):
        """测试连接接口不做协议校验（服务层负责），但超长地址仍被拦截"""
        resp = client.post("/model-provider/test-connection", json={"base_url": "https://a.com/" + "x" * 600})

        assert resp.json.get("code") == HttpCode.VALIDATE_ERROR
