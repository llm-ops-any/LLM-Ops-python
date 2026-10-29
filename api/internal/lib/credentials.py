#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : credentials.py
@Desc    : API插件请求头（Authorization: Bearer xxx 等）的加密存储、解密与对外掩码

说明：
1. 存储格式 [{key, value, encrypted}]：value 为密文时 encrypted=True；
   历史数据没有 encrypted 字段，一律按明文处理，下次更新时自动转成密文；
2. 对外响应只给掩码（value="****" + has_value），任何响应体都不出现键值明文；
3. 更新时 value 传空字符串（或掩码占位符）表示「沿用已保存的密钥」，
   避免用户只想改个插件名就必须把密钥重新抄一遍。
"""
import logging
from typing import Optional

from internal.lib.secret import encrypt_secret, decrypt_secret

logger = logging.getLogger(__name__)

# 页面展示用的掩码，与模型供应商/语音服务的密钥掩码保持一致
MASKED_VALUE = "****"


def encrypt_headers(
        headers: Optional[list[dict]],
        existing_headers: Optional[list[dict]] = None,
) -> list[dict]:
    """把待保存的请求头转成加密存储格式

    Args:
        headers: 本次提交的请求头，value 为空表示沿用 existing_headers 中的同名声明的密钥
        existing_headers: 数据库中已存的请求头（可能是密文，也可能是历史明文）

    Returns:
        可直接落库的请求头列表
    """
    existing = {
        (header.get("key") or ""): header
        for header in (existing_headers or [])
        if isinstance(header, dict)
    }

    result = []
    for header in (headers or []):
        if not isinstance(header, dict):
            continue

        key = (header.get("key") or "").strip()
        value = header.get("value") or ""
        if not isinstance(value, str):
            value = str(value)

        # 1.value为空或仍是掩码占位，表示不修改该请求头的密钥
        if value.strip() == "" or value.strip() == MASKED_VALUE:
            stored = existing.get(key) or {}
            stored_value = stored.get("value") or ""
            if stored_value and not stored.get("encrypted"):
                # 历史明文数据顺带转成密文，不必等专门的迁移脚本
                result.append({"key": key, "value": encrypt_secret(stored_value), "encrypted": True})
            elif stored_value:
                result.append({"key": key, "value": stored_value, "encrypted": True})
            else:
                result.append({"key": key, "value": "", "encrypted": False})
            continue

        # 2.传入了新的键值，加密后再落库
        result.append({"key": key, "value": encrypt_secret(value), "encrypted": True})

    return result


def decrypt_headers(headers: Optional[list[dict]]) -> list[dict]:
    """把存储格式的请求头还原成明文，仅供发起真实请求使用

    禁止把本函数的返回值放进任何接口响应。
    """
    result = []
    for header in (headers or []):
        if not isinstance(header, dict):
            continue

        key = header.get("key") or ""
        value = header.get("value") or ""

        # 1.历史数据没有加密标记，按明文直接使用
        if not header.get("encrypted"):
            result.append({"key": key, "value": value})
            continue

        # 2.密文解不开(主密钥变更)时降级为空值，让请求照常发出并由上游返回鉴权失败，不抛异常
        plain_text = decrypt_secret(value)
        if plain_text is None:
            logger.warning("API插件的请求头解密失败，key=%s，请到工具页面重新填写该密钥", key)
            plain_text = ""
        result.append({"key": key, "value": plain_text})

    return result


def mask_headers(headers: Optional[list[dict]]) -> list[dict]:
    """把存储格式的请求头转成展示用的掩码结构，不返回任何键值明文"""
    result = []
    for header in (headers or []):
        if not isinstance(header, dict):
            continue

        key = header.get("key") or ""
        has_value = bool(header.get("value"))
        result.append({
            "key": key,
            "value": MASKED_VALUE if has_value else "",
            "has_value": has_value,
        })

    return result
