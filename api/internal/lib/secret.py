#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : secret.py
@Desc    : 平台敏感配置（大模型API Key等）的对称加密与解密

说明：
1. 主密钥由现有环境变量 JWT_SECRET_KEY 派生，不新增环境变量，避免部署时漏配；
2. 派生方式固定为 sha256(固定前缀 + JWT_SECRET_KEY) 后做 urlsafe base64，
   保证同一台机器同一份env下加解密结果稳定；
3. 解密失败一律返回None由调用方降级处理，绝不把异常抛给业务链路。
"""
import base64
import hashlib
import logging
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

# 派生主密钥时使用的固定前缀，更换它等于让所有历史密文失效，禁止修改
_SECRET_NAMESPACE = "llmops:platform-setting:"


def _build_fernet() -> Fernet:
    """由JWT_SECRET_KEY派生Fernet实例，用于加解密平台敏感配置"""
    secret_key = os.getenv("JWT_SECRET_KEY") or ""
    if not secret_key:
        # 说明：JWT_SECRET_KEY缺失时仍给出确定性的密钥，保证功能可用；
        #      此时密文强度依赖本固定串，属于部署配置缺失场景，需在部署文档中要求配置。
        logging.warning("环境变量JWT_SECRET_KEY缺失，平台敏感配置的加密强度将降级")

    digest = hashlib.sha256(f"{_SECRET_NAMESPACE}{secret_key}".encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain_text: str) -> str:
    """加密明文信息，传入空字符串时返回空字符串"""
    if not plain_text:
        return ""
    return _build_fernet().encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_secret(cipher_text: str) -> Optional[str]:
    """解密密文信息，解密失败返回None(调用方据此降级，不抛异常)"""
    if not cipher_text:
        return ""
    try:
        return _build_fernet().decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError, TypeError):
        # 说明：主密钥变更(如更换JWT_SECRET_KEY)会让历史密文无法解开，
        #      此处只记告警不抛异常，由上层提示用户重新填写。
        logging.warning("平台敏感配置解密失败，可能是JWT_SECRET_KEY已变更，需重新填写配置")
        return None
