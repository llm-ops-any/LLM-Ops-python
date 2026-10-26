#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : test_model_provider_service.py
@Desc    : 大模型凭证配置服务单元测试（CR-16102600）

覆盖点：
1. 库内无配置 → 回退环境变量，来源标记 environment；
2. 保存后立即生效（source=database），密钥以密文落库、明文不出现在存储值里；
3. api_key 留空保存 = 只改地址、保留原密钥；
4. 掩码接口只回 `****`，任何字段都不含明文；
5. 密文解不开（主密钥变更）→ 回退环境变量并标记 invalid；
6. 进程内 TTL 缓存：TTL 内不重复查库，force_refresh 才重新查；
7. test_connection 的七个分支（缺地址/非 http/缺 key/200/空列表/401/404/超时/不可达）。

说明：
- 用轻量 FakeDB 代替真实库，用例不读写真实配置，也不联网（requests.get 全部被替换）；
- 所有密钥都是假值 `sk-test-*`，不会输出真实凭证。
"""
import json

import pytest
import requests

from internal.model import PlatformSetting
from internal.service.model_provider_service import (
    MASKED_API_KEY,
    SOURCE_DATABASE,
    SOURCE_ENVIRONMENT,
    SOURCE_INVALID,
    ModelProviderService,
)

ENV_BASE_URL = "https://env.example.com/v1/"
ENV_API_KEY = "sk-test-env-fake-key"


class _FakeSetting:
    """替身配置记录，仅保留本服务用到的两个字段"""

    def __init__(self, name: str, value: str):
        self.name = name
        self.value = value


class _FakeQuery:
    """替身查询对象，filter 一律放行，first 返回唯一一条记录"""

    def __init__(self, session: "_FakeSession"):
        self._session = session

    def filter(self, *args, **kwargs):  # noqa: ARG002
        return self

    def first(self):
        return next(iter(self._session.rows.values()), None)


class _FakeSession:
    """替身会话，记录查询次数、写入与提交次数"""

    def __init__(self):
        self.rows: dict = {}
        self.query_count = 0
        self.commit_count = 0

    def query(self, model):  # noqa: ARG002
        self.query_count += 1
        return _FakeQuery(self)

    def add(self, obj):
        self.rows[obj.name] = obj

    def commit(self):
        self.commit_count += 1


class _FakeDB:
    """替身数据库，仅暴露 session"""

    def __init__(self):
        self.session = _FakeSession()


def _make_setting(value: str) -> PlatformSetting:
    """构造一条 platform_setting 记录（不落库）"""
    return PlatformSetting(name="model_provider", value=value)


@pytest.fixture(autouse=True)
def _clear_config_cache():
    """每个用例前后清空进程内缓存，避免用例之间互相影响"""
    ModelProviderService.clear_cache()
    yield
    ModelProviderService.clear_cache()


@pytest.fixture
def env_credentials(monkeypatch):
    """固定环境变量兜底值（假值）"""
    monkeypatch.setenv("OPENAI_API_BASE", ENV_BASE_URL)
    monkeypatch.setenv("OPENAI_API_KEY", ENV_API_KEY)


@pytest.fixture
def service(app, env_credentials):
    """提供处于应用上下文内的服务实例与替身数据库"""
    fake_db = _FakeDB()
    with app.app_context():
        yield ModelProviderService(db=fake_db), fake_db


class TestLoadConfig:
    """配置加载与来源判定"""

    def test_falls_back_to_environment_when_no_record(self, service):
        """库里没有配置时读环境变量，来源标 environment"""
        svc, fake_db = service

        config = svc.get_active_config()

        assert fake_db.session.query_count == 1
        assert config.source == SOURCE_ENVIRONMENT
        assert config.base_url == "https://env.example.com/v1"  # 结尾斜杠已去掉
        assert config.api_key == ENV_API_KEY
        assert config.has_api_key is True

    def test_save_then_active_config_reads_database(self, service):
        """保存后生效来源为 database，密钥以密文落库"""
        svc, fake_db = service

        svc.save_config(" https://db.example.com/v1/ ", " sk-test-db-fake ")

        stored_value = fake_db.session.rows["model_provider"].value
        config = svc.get_active_config(force_refresh=True)

        assert config.source == SOURCE_DATABASE
        assert config.base_url == "https://db.example.com/v1"
        assert config.api_key == "sk-test-db-fake"  # Key 已去掉首尾空白
        assert "sk-test-db-fake" not in stored_value  # 明文不落库
        assert "api_key_cipher" in json.loads(stored_value)
        assert fake_db.session.commit_count == 1

    def test_empty_api_key_keeps_previous_key(self, service):
        """api_key 留空保存表示只改地址，原密钥保留"""
        svc, _ = service
        svc.save_config("https://db.example.com/v1", "sk-test-keep-me")

        svc.save_config("https://db.example.com/v2", "")

        config = svc.get_active_config(force_refresh=True)
        assert config.base_url == "https://db.example.com/v2"
        assert config.api_key == "sk-test-keep-me"

    def test_decrypt_failure_falls_back_and_marks_invalid(self, service, monkeypatch):
        """密文解不开（换过 JWT_SECRET_KEY）时回退环境变量并标记 invalid"""
        _, fake_db = service
        fake_db.session.rows["model_provider"] = _make_setting(
            json.dumps({"base_url": "https://db.example.com/v1", "api_key_cipher": "broken-cipher"})
        )
        ModelProviderService.clear_cache()

        config = ModelProviderService(db=fake_db).get_active_config()

        assert config.source == SOURCE_INVALID
        assert config.api_key == ENV_API_KEY
        assert config.base_url == "https://db.example.com/v1"

    def test_broken_json_falls_back_to_environment(self, service):
        """库里的值不是合法 JSON 时按未配置处理，不能抛异常"""
        svc, fake_db = service
        fake_db.session.rows["model_provider"] = _make_setting("not-a-json")
        ModelProviderService.clear_cache()

        config = ModelProviderService(db=fake_db).get_active_config()

        assert config.source == SOURCE_ENVIRONMENT
        assert config.api_key == ENV_API_KEY


class TestCache:
    """进程内 TTL 缓存行为"""

    def test_ttl_hits_cache_without_db_query(self, service):
        """TTL 内连续读取不重复查库"""
        svc, fake_db = service

        first = svc.get_active_config()
        second = svc.get_active_config()

        assert fake_db.session.query_count == 1
        assert first is second

    def test_force_refresh_queries_db_again(self, service):
        """force_refresh=True 时强制重新查库"""
        svc, fake_db = service

        svc.get_active_config()
        svc.get_active_config(force_refresh=True)

        assert fake_db.session.query_count == 2

    def test_clear_cache_triggers_reload(self, service):
        """清缓存后重新查库，保证保存后 10 秒内生效"""
        svc, fake_db = service

        svc.get_active_config()
        ModelProviderService.clear_cache()
        svc.get_active_config()

        assert fake_db.session.query_count == 2


class TestMaskedSetting:
    """掩码展示：永不返回明文"""

    def test_masked_setting_never_contains_plaintext(self, service):
        """掩码接口只给 ****，序列化结果不含明文密钥"""
        svc, _ = service
        svc.save_config("https://db.example.com/v1", "sk-test-secret-value")

        setting = svc.get_masked_setting()
        serialized = json.dumps(setting, ensure_ascii=False)

        assert setting["masked_api_key"] == MASKED_API_KEY
        assert setting["has_api_key"] is True
        assert setting["source"] == SOURCE_DATABASE
        assert "sk-test-secret-value" not in serialized

    def test_masked_setting_without_key(self, service, monkeypatch):
        """没有可用密钥时掩码为空、has_api_key 为 False"""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        ModelProviderService.clear_cache()
        svc, _ = service

        setting = svc.get_masked_setting()

        assert setting["masked_api_key"] == ""
        assert setting["has_api_key"] is False


class TestBaseUrlNormalize:
    """API 地址规范化"""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("https://a.com/v1/", "https://a.com/v1"),
            ("  https://a.com/v1  ", "https://a.com/v1"),
            ("https://a.com", "https://a.com"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize(self, raw, expected):
        """去首尾空白与结尾斜杠，None 视为空串"""
        assert ModelProviderService._normalize_base_url(raw) == expected


class _FakeResponse:
    """替身 HTTP 响应"""

    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class TestConnection:
    """连通性测试的各个分支"""

    def _patch_get(self, monkeypatch, response=None, exc=None):
        """替换 requests.get，记录调用参数"""
        calls = []

        def fake_get(url, headers=None, timeout=None):
            calls.append({"url": url, "headers": headers or {}, "timeout": timeout})
            if exc is not None:
                raise exc
            return response

        monkeypatch.setattr("internal.service.model_provider_service.requests.get", fake_get)
        return calls

    def test_missing_base_url(self, service, monkeypatch):
        """已保存配置与入参都没有地址时先提示填地址"""
        svc, _ = service
        monkeypatch.delenv("OPENAI_API_BASE", raising=False)
        ModelProviderService.clear_cache()

        result = svc.test_connection(base_url="", api_key="sk-test-x")

        assert result["ok"] is False
        assert "API地址" in result["message"]

    def test_invalid_scheme(self, service, monkeypatch):
        """地址不是 http(s) 前缀时直接拒绝，不发请求"""
        svc, _ = service
        calls = self._patch_get(monkeypatch, _FakeResponse(200, {"data": [1]}))

        result = svc.test_connection(base_url="ftp://a.com/v1", api_key="sk-test-x")

        assert result["ok"] is False
        assert "http://" in result["message"]
        assert calls == []

    def test_missing_api_key(self, service, monkeypatch):
        """没有可用密钥时提示填 Key"""
        svc, _ = service
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        ModelProviderService.clear_cache()

        result = svc.test_connection(base_url="https://a.com/v1", api_key="")

        assert result["ok"] is False
        assert "API Key" in result["message"]

    def test_success(self, service, monkeypatch):
        """200 且有模型列表 → 成功并返回模型数量"""
        svc, _ = service
        calls = self._patch_get(monkeypatch, _FakeResponse(200, {"data": [{}, {}, {}]}))

        result = svc.test_connection(base_url="https://a.com/v1/", api_key="sk-test-x")

        assert result["ok"] is True
        assert result["model_count"] == 3
        assert calls[0]["url"] == "https://a.com/v1/models"
        assert calls[0]["headers"]["Authorization"] == "Bearer sk-test-x"

    def test_empty_model_list_hints_v1(self, service, monkeypatch):
        """200 但没有模型列表 → 提示可能缺 /v1"""
        svc, _ = service
        self._patch_get(monkeypatch, _FakeResponse(200, {"data": []}))

        result = svc.test_connection(base_url="https://a.com", api_key="sk-test-x")

        assert result["ok"] is False
        assert "/v1" in result["message"]

    def test_unauthorized(self, service, monkeypatch):
        """401/403 → 密钥无效"""
        svc, _ = service
        self._patch_get(monkeypatch, _FakeResponse(401))

        result = svc.test_connection(base_url="https://a.com/v1", api_key="sk-test-bad")

        assert result["ok"] is False
        assert result["status"] == 401
        assert "Key" in result["message"]

    def test_not_found(self, service, monkeypatch):
        """404 → 接口不存在，提示检查 /v1"""
        svc, _ = service
        self._patch_get(monkeypatch, _FakeResponse(404))

        result = svc.test_connection(base_url="https://a.com", api_key="sk-test-x")

        assert result["ok"] is False
        assert result["status"] == 404
        assert "/v1" in result["message"]

    def test_timeout(self, service, monkeypatch):
        """超时单独提示，不误导成密钥错误"""
        svc, _ = service
        self._patch_get(monkeypatch, exc=requests.Timeout())

        result = svc.test_connection(base_url="https://a.com/v1", api_key="sk-test-x")

        assert result["ok"] is False
        assert "超时" in result["message"]

    def test_connection_error(self, service, monkeypatch):
        """网络不可达 → 提示检查地址"""
        svc, _ = service
        self._patch_get(monkeypatch, exc=requests.ConnectionError())

        result = svc.test_connection(base_url="https://a.com/v1", api_key="sk-test-x")

        assert result["ok"] is False
        assert "无法连接" in result["message"]

    def test_uses_saved_config_when_args_empty(self, service, monkeypatch):
        """入参为空时用已保存的地址与密钥探测，且不落库"""
        svc, fake_db = service
        svc.save_config("https://saved.example.com/v1", "sk-test-saved")
        calls = self._patch_get(monkeypatch, _FakeResponse(200, {"data": [{}]}))
        commits_before = fake_db.session.commit_count

        result = svc.test_connection()

        assert result["ok"] is True
        assert calls[0]["url"] == "https://saved.example.com/v1/models"
        assert calls[0]["headers"]["Authorization"] == "Bearer sk-test-saved"
        assert fake_db.session.commit_count == commits_before  # 测试连接不落库
