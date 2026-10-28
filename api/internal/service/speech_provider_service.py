#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : speech_provider_service.py
@Desc    : 语音服务配置的读写（CR-16102803）

设计说明（与 model_provider_service 保持同一套路，见 D-04）：
1. 配置存 platform_setting 表，name=speech_provider，value 为 JSON；
2. 阿里百炼 API Key 用 lib/secret 加密后存 dashscope_api_key_cipher，接口只回显掩码；
3. 读取带进程内 5 秒 TTL 缓存，保存后清缓存，保证「页面改完 10 秒内生效」（AC-02）；
4. 库里没有配置时回退环境变量 DASHSCOPE_API_KEY / DASHSCOPE_OMNI_HOST。
"""
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

from flask import has_app_context
from injector import inject

from internal.entity.audio_entity import AudioEngine, DEFAULT_SPEECH_CONFIG
from internal.lib.secret import decrypt_secret, encrypt_secret
from internal.model import PlatformSetting
from pkg.sqlalchemy import SQLAlchemy
from .base_service import BaseService

# 设置项在 platform_setting 表中的名称
SETTING_NAME = "speech_provider"
# 进程内缓存有效期(秒)
CACHE_TTL_SECONDS = 5
# 页面展示用的掩码
MASKED_API_KEY = "****"
# 配置来源
SOURCE_DATABASE = "database"
SOURCE_ENVIRONMENT = "environment"
SOURCE_INVALID = "invalid"

# 进程内缓存，多 worker 各自持有，靠 TTL 收敛
_CACHE = {"expires_at": 0.0, "config": None}

_SOURCE_LABELS = {
    SOURCE_DATABASE: "数据库配置",
    SOURCE_ENVIRONMENT: "环境变量兜底",
    SOURCE_INVALID: "数据库配置(密钥已失效)",
}


@dataclass
class SpeechProviderConfig:
    """语音服务配置（解密后的运行时视图）"""
    engine: str = AudioEngine.BROWSER.value
    api_key: str = ""
    omni_model: str = DEFAULT_SPEECH_CONFIG["omni_model"]
    omni_voice: str = DEFAULT_SPEECH_CONFIG["omni_voice"]
    omni_host: str = DEFAULT_SPEECH_CONFIG["omni_host"]
    cosyvoice_model: str = DEFAULT_SPEECH_CONFIG["cosyvoice_model"]
    cosyvoice_voice: str = DEFAULT_SPEECH_CONFIG["cosyvoice_voice"]
    paraformer_model: str = DEFAULT_SPEECH_CONFIG["paraformer_model"]
    source: str = SOURCE_ENVIRONMENT
    extra: dict = field(default_factory=dict)

    @property
    def has_api_key(self) -> bool:
        """是否已配置可用的 API Key"""
        return bool(self.api_key)

    @property
    def source_label(self) -> str:
        """配置来源的中文描述"""
        return _SOURCE_LABELS.get(self.source, "未知来源")

    @property
    def is_browser(self) -> bool:
        """是否为浏览器引擎（后端不参与合成）"""
        return self.engine == AudioEngine.BROWSER.value


@inject
@dataclass
class SpeechProviderService(BaseService):
    """语音服务配置服务"""
    db: SQLAlchemy

    # ---------------------------------------------------------------- 读取

    def _read_payload(self) -> Optional[dict]:
        """从数据库读取配置载荷，未配置时返回 None"""
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

    @staticmethod
    def _pick(payload: dict, key: str, default: str) -> str:
        """取字符串配置项，空值回退默认"""
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else default

    def _load_config(self) -> SpeechProviderConfig:
        """加载当前生效的语音配置，数据库优先，其次环境变量"""
        payload: Optional[dict] = None
        try:
            payload = self._read_payload()
        except Exception:
            # 表未建/数据库暂不可用时不能让语音接口挂掉，降级读环境变量
            logging.warning("读取语音服务配置失败，回退环境变量兜底", exc_info=True)

        env_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
        env_host = (os.getenv("DASHSCOPE_OMNI_HOST") or "").strip() or DEFAULT_SPEECH_CONFIG["omni_host"]

        if payload is None:
            return SpeechProviderConfig(api_key=env_key, omni_host=env_host, source=SOURCE_ENVIRONMENT)

        cipher_text = payload.get("dashscope_api_key_cipher") or ""
        db_key = ""
        source = SOURCE_DATABASE
        if cipher_text:
            decrypted = decrypt_secret(cipher_text)
            if decrypted is None:
                # 密文解不开(主密钥变更)，回退环境变量并标记失效
                source = SOURCE_INVALID
            else:
                db_key = decrypted

        engine = self._pick(payload, "engine", DEFAULT_SPEECH_CONFIG["engine"])
        if engine not in {item.value for item in AudioEngine}:
            engine = DEFAULT_SPEECH_CONFIG["engine"]

        return SpeechProviderConfig(
            engine=engine,
            api_key=db_key or env_key,
            omni_model=self._pick(payload, "omni_model", DEFAULT_SPEECH_CONFIG["omni_model"]),
            omni_voice=self._pick(payload, "omni_voice", DEFAULT_SPEECH_CONFIG["omni_voice"]),
            omni_host=self._pick(payload, "omni_host", DEFAULT_SPEECH_CONFIG["omni_host"]) or env_host,
            cosyvoice_model=self._pick(payload, "cosyvoice_model", DEFAULT_SPEECH_CONFIG["cosyvoice_model"]),
            cosyvoice_voice=self._pick(payload, "cosyvoice_voice", DEFAULT_SPEECH_CONFIG["cosyvoice_voice"]),
            paraformer_model=self._pick(payload, "paraformer_model", DEFAULT_SPEECH_CONFIG["paraformer_model"]),
            source=source,
        )

    def get_active_config(self, force_refresh: bool = False) -> SpeechProviderConfig:
        """获取当前生效的语音配置(带进程内缓存)"""
        # 应用上下文未就绪时不查库也不写缓存，避免把兜底配置缓存住
        if not has_app_context():
            return SpeechProviderConfig(
                api_key=(os.getenv("DASHSCOPE_API_KEY") or "").strip(),
                omni_host=(os.getenv("DASHSCOPE_OMNI_HOST") or "").strip() or DEFAULT_SPEECH_CONFIG["omni_host"],
                source=SOURCE_ENVIRONMENT,
            )

        cached = _CACHE.get("config")
        if not force_refresh and cached is not None and time.monotonic() < _CACHE.get("expires_at", 0.0):
            return cached

        config = self._load_config()
        _CACHE["config"] = config
        _CACHE["expires_at"] = time.monotonic() + CACHE_TTL_SECONDS
        return config

    @staticmethod
    def clear_cache() -> None:
        """清空进程内缓存，保存配置后调用"""
        _CACHE["config"] = None
        _CACHE["expires_at"] = 0.0

    # ---------------------------------------------------------------- 写入

    def save_config(self, **kwargs) -> SpeechProviderConfig:
        """保存配置；dashscope_api_key 为空表示不修改已存的密钥

        只更新显式传入的键，未传的保持原值 —— 避免前端只切引擎时把模型名清空。
        """
        payload = self._read_payload() or {}

        api_key = (kwargs.get("dashscope_api_key") or "").strip()
        if api_key:
            payload["dashscope_api_key_cipher"] = encrypt_secret(api_key)

        for key in (
            "engine",
            "omni_model",
            "omni_voice",
            "omni_host",
            "cosyvoice_model",
            "cosyvoice_voice",
            "paraformer_model",
        ):
            value = kwargs.get(key)
            if isinstance(value, str) and value.strip():
                payload[key] = value.strip()

        value = json.dumps(payload, ensure_ascii=False)
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

    # ---------------------------------------------------------------- 连通性

    def test_connection(self) -> dict:
        """测试当前引擎能否真的出声（不落库、不改配置）

        返回 {"ok": bool, "engine": str, "message": str, "bytes": int}。
        浏览器引擎不需要测（合成在浏览器侧完成），直接返回 ok。
        """
        config = self.get_active_config()

        if config.is_browser:
            return {
                "ok": True,
                "engine": config.engine,
                "message": "浏览器引擎无需测试，朗读由浏览器完成",
                "bytes": 0,
            }

        if not config.has_api_key:
            return {
                "ok": False,
                "engine": config.engine,
                "message": "请先填写阿里百炼 API Key",
                "bytes": 0,
            }

        if config.engine == AudioEngine.OMNI.value:
            return self._test_omni(config)
        return self._test_dashscope(config)

    def _test_omni(self, config: SpeechProviderConfig) -> dict:
        """只建连并等 session.created，不触发合成（零计费）"""
        import websocket

        host = (config.omni_host or "").strip() or DEFAULT_SPEECH_CONFIG["omni_host"]
        url = f"wss://{host}/api-ws/v1/realtime?model={(config.omni_model or '').strip()}"
        try:
            ws = websocket.create_connection(
                url,
                header=[f"Authorization: Bearer {config.api_key}"],
                timeout=10,
            )
        except Exception as error:  # noqa: BLE001
            logging.warning("Omni-Realtime 连接测试失败: %s", error)
            return {"ok": False, "engine": config.engine, "message": "连接失败，请检查主机域名与 API Key", "bytes": 0}

        try:
            for _ in range(3):
                raw = ws.recv()
                if raw and '"session.created"' in str(raw):
                    return {"ok": True, "engine": config.engine, "message": "连接成功", "bytes": 0}
            return {"ok": False, "engine": config.engine, "message": "已连接但未返回会话信息", "bytes": 0}
        except Exception as error:  # noqa: BLE001
            logging.warning("Omni-Realtime 会话测试失败: %s", error)
            return {"ok": False, "engine": config.engine, "message": "会话建立超时", "bytes": 0}
        finally:
            try:
                ws.close()
            except Exception:
                pass

    @staticmethod
    def _test_dashscope(config: SpeechProviderConfig) -> dict:
        """合成两个字并检查是否有音频返回（P-04 的 0 字节问题靠这条兜）"""
        try:
            import dashscope
            from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

            dashscope.api_key = config.api_key
            synthesizer = SpeechSynthesizer(
                model=(config.cosyvoice_model or "").strip(),
                voice=(config.cosyvoice_voice or "").strip(),
                format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            )
            audio = synthesizer.call("测试")
            size = len(audio) if audio else 0
        except Exception as error:  # noqa: BLE001
            logging.warning("CosyVoice 连通性测试异常: %s", error)
            return {"ok": False, "engine": config.engine, "message": f"合成异常：{error}", "bytes": 0}

        if size == 0:
            # 说明：模型/音色不可用时 SDK 不抛异常、只返回空音频（前置资源 P-04）
            return {
                "ok": False,
                "engine": config.engine,
                "message": "合成返回空音频，请检查模型与音色是否可用",
                "bytes": 0,
            }
        return {
            "ok": True,
            "engine": config.engine,
            "message": f"合成成功，返回 {size} 字节音频",
            "bytes": size,
        }

    def get_masked_setting(self) -> dict:
        """获取用于页面展示的配置，永不返回密钥明文（AC-01）"""
        config = self.get_active_config()

        return {
            "engine": config.engine,
            "has_api_key": config.has_api_key,
            "masked_api_key": MASKED_API_KEY if config.has_api_key else "",
            "omni_model": config.omni_model,
            "omni_voice": config.omni_voice,
            "omni_host": config.omni_host,
            "cosyvoice_model": config.cosyvoice_model,
            "cosyvoice_voice": config.cosyvoice_voice,
            "paraformer_model": config.paraformer_model,
            "source": config.source,
            "source_label": config.source_label,
        }
