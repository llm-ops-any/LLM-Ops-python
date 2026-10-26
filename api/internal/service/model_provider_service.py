#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : model_provider_service.py
@Desc    : 大模型服务凭证配置服务，负责API地址与API Key的读写、加密存储与连通性测试

设计说明：
1. 配置存放在platform_setting表(name=model_provider)，value为JSON字符串；
2. API Key以Fernet密文存储，接口与页面永不回显明文；
3. 读取时带进程内5秒TTL缓存，保证"页面保存后10秒内生效"且不必每次请求打库；
4. 库中无配置时回退环境变量(OPENAI_API_BASE/OPENAI_API_KEY)，解密失败则视为密钥失效。
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests
from flask import has_app_context
from injector import inject

from internal.lib.secret import decrypt_secret, encrypt_secret
from internal.model import PlatformSetting
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

# 设置项在platform_setting表中的名称
SETTING_NAME = "model_provider"
# 进程内缓存有效期(秒)，需小于需求约定的10秒生效上限
CACHE_TTL_SECONDS = 5
# 测试连接的超时时间(秒)
TEST_CONNECTION_TIMEOUT = 15
# 配置来源
SOURCE_DATABASE = "database"
SOURCE_ENVIRONMENT = "environment"
SOURCE_INVALID = "invalid"
# 页面展示用的掩码，固定4个星号
MASKED_API_KEY = "****"

# 进程内缓存，多worker各自持有，靠TTL收敛
_CACHE: dict = {"expires_at": 0.0, "config": None}


@dataclass
class ProviderConfig:
    """大模型服务凭证配置"""
    base_url: str = ""
    api_key: str = ""
    source: str = SOURCE_ENVIRONMENT

    @property
    def has_api_key(self) -> bool:
        """是否已配置可用的API Key"""
        return bool(self.api_key)

    @property
    def source_label(self) -> str:
        """配置来源的中文描述"""
        return {
            SOURCE_DATABASE: "数据库配置",
            SOURCE_ENVIRONMENT: "环境变量兜底",
            SOURCE_INVALID: "数据库配置(密钥已失效)",
        }.get(self.source, "未知来源")


@inject
@dataclass
class ModelProviderService(BaseService):
    """大模型服务凭证配置服务"""
    db: SQLAlchemy

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """规范化API地址，去掉首尾空白与结尾斜杠"""
        return (base_url or "").strip().rstrip("/")

    def _read_payload(self) -> Optional[dict]:
        """从数据库读取配置载荷，未配置时返回None"""
        setting = (
            self.db.session.query(PlatformSetting)
            .filter(PlatformSetting.name == SETTING_NAME)
            .first()
        )
        if setting is None:
            return None
        try:
            payload = json.loads(setting.value or "{}")
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _load_config(self) -> ProviderConfig:
        """加载当前生效的凭证配置，数据库优先，其次环境变量"""
        payload: Optional[dict] = None
        try:
            payload = self._read_payload()
        except Exception:
            # 说明：表未建/数据库暂时不可用时不能让对话链路挂掉，降级读环境变量
            logging.warning("读取平台级大模型配置失败，回退环境变量兜底", exc_info=True)

        env_base_url = self._normalize_base_url(os.getenv("OPENAI_API_BASE") or "")
        env_api_key = os.getenv("OPENAI_API_KEY") or ""

        if payload is None:
            return ProviderConfig(base_url=env_base_url, api_key=env_api_key, source=SOURCE_ENVIRONMENT)

        db_base_url = self._normalize_base_url(payload.get("base_url") or "")
        cipher_text = payload.get("api_key_cipher") or ""
        db_api_key = ""
        if cipher_text:
            decrypted = decrypt_secret(cipher_text)
            if decrypted is None:
                # 说明：密文解不开(主密钥变更)，回退环境变量并标记失效状态
                return ProviderConfig(base_url=db_base_url or env_base_url, api_key=env_api_key, source=SOURCE_INVALID)
            db_api_key = decrypted

        return ProviderConfig(
            base_url=db_base_url or env_base_url,
            api_key=db_api_key or env_api_key,
            source=SOURCE_DATABASE,
        )

    def get_active_config(self, force_refresh: bool = False) -> ProviderConfig:
        """获取当前生效的凭证配置(带进程内缓存)"""
        # 说明：应用上下文未就绪时(如进程启动阶段构造模型实例)直接读环境变量，
        #      不查库也不写缓存，避免把兜底配置缓存住导致页面配置短时失效
        if not has_app_context():
            return _environment_config()

        cached_config = _CACHE.get("config")
        if not force_refresh and cached_config is not None and time.monotonic() < _CACHE.get("expires_at", 0.0):
            return cached_config

        config = self._load_config()
        _CACHE["config"] = config
        _CACHE["expires_at"] = time.monotonic() + CACHE_TTL_SECONDS
        return config

    @staticmethod
    def clear_cache() -> None:
        """清空进程内缓存，保存配置后调用"""
        _CACHE["config"] = None
        _CACHE["expires_at"] = 0.0

    def save_config(self, base_url: str, api_key: Optional[str] = None) -> ProviderConfig:
        """保存配置，api_key为空表示不修改已存储的密钥"""
        payload = self._read_payload() or {}
        cipher_text = payload.get("api_key_cipher") or ""
        if api_key:
            cipher_text = encrypt_secret(api_key.strip())

        value = json.dumps(
            {"base_url": self._normalize_base_url(base_url), "api_key_cipher": cipher_text},
            ensure_ascii=False,
        )

        setting = (
            self.db.session.query(PlatformSetting)
            .filter(PlatformSetting.name == SETTING_NAME)
            .first()
        )
        if setting is None:
            setting = PlatformSetting(name=SETTING_NAME, value=value)
            self.db.session.add(setting)
        else:
            setting.value = value
        self.db.session.commit()

        self.clear_cache()
        return self.get_active_config(force_refresh=True)

    def get_masked_setting(self) -> dict:
        """获取用于页面展示的配置信息，永不返回密钥明文"""
        config = self.get_active_config()
        return {
            "base_url": config.base_url,
            "has_api_key": config.has_api_key,
            "masked_api_key": MASKED_API_KEY if config.has_api_key else "",
            "source": config.source,
            "source_label": config.source_label,
        }

    def test_connection(self, base_url: Optional[str] = None, api_key: Optional[str] = None) -> dict:
        """测试连通性，未传参数时使用已保存的配置，仅探测不落库"""
        config = self.get_active_config()
        target_base_url = self._normalize_base_url(base_url or config.base_url)
        target_api_key = (api_key or "").strip() or config.api_key

        if not target_base_url:
            return {"ok": False, "status": 0, "message": "请先填写API地址", "model_count": 0}
        if not target_base_url.startswith(("http://", "https://")):
            return {"ok": False, "status": 0, "message": "API地址必须以http://或https://开头", "model_count": 0}
        if not target_api_key:
            return {"ok": False, "status": 0, "message": "请先填写API Key", "model_count": 0}

        try:
            response = requests.get(
                f"{target_base_url}/models",
                headers={"Authorization": f"Bearer {target_api_key}"},
                timeout=TEST_CONNECTION_TIMEOUT,
            )
        except requests.Timeout:
            return {
                "ok": False,
                "status": 0,
                "message": f"连接超时(超过{TEST_CONNECTION_TIMEOUT}秒)，请检查地址与网络，超时不代表密钥错误",
                "model_count": 0,
            }
        except requests.RequestException:
            return {"ok": False, "status": 0, "message": "无法连接到该地址，请检查地址是否正确", "model_count": 0}

        if response.status_code == 200:
            try:
                model_count = len(response.json().get("data") or [])
            except ValueError:
                model_count = 0
            if model_count == 0:
                return {
                    "ok": False,
                    "status": 200,
                    "message": "地址可访问但未返回模型列表，请确认地址是否以/v1结尾",
                    "model_count": 0,
                }
            return {"ok": True, "status": 200, "message": f"连接成功，共{model_count}个模型", "model_count": model_count}
        if response.status_code in (401, 403):
            return {"ok": False, "status": response.status_code, "message": "API Key无效或无权访问", "model_count": 0}
        if response.status_code == 404:
            return {"ok": False, "status": 404, "message": "接口不存在，请确认地址是否以/v1结尾", "model_count": 0}
        return {
            "ok": False,
            "status": response.status_code,
            "message": f"接口返回异常状态码{response.status_code}",
            "model_count": 0,
        }


def _environment_config() -> ProviderConfig:
    """基于环境变量构造凭证配置，作为所有异常场景的兜底"""
    return ProviderConfig(
        base_url=(os.getenv("OPENAI_API_BASE") or "").strip().rstrip("/"),
        api_key=os.getenv("OPENAI_API_KEY") or "",
        source=SOURCE_ENVIRONMENT,
    )


def get_active_config(force_refresh: bool = False) -> ProviderConfig:
    """获取当前生效的凭证配置(供语言模型、向量化等底层模块调用)

    说明：底层模块(providers/uino/chat.py、embeddings_service)通过本函数跟随页面配置，
        应用上下文未就绪或读取异常时一律降级为环境变量，保证不影响对话主链路。
    """
    if not has_app_context():
        return _environment_config()

    try:
        from app.http.module import injector
        return injector.get(ModelProviderService).get_active_config(force_refresh=force_refresh)
    except Exception:
        logging.warning("获取大模型凭证配置失败，回退环境变量兜底", exc_info=True)
        return _environment_config()
