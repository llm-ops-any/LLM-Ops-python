#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : test_secret.py
@Desc    : 平台敏感配置加解密单元测试（CR-16102600）

覆盖点：
1. 正常往返；
2. 空值处理（空串进空串出）；
3. 密文不含明文、同一明文两次加密结果不同（Fernet 随机 IV）；
4. 非法密文 / 更换 JWT_SECRET_KEY 后解密返回 None（由调用方降级），不抛异常。

注意：用例中的密钥全部是假值，测试不读写真实凭证。
"""
import pytest

from internal.lib.secret import decrypt_secret, encrypt_secret


class TestSecret:
    """加解密工具测试类"""

    def test_roundtrip(self):
        """正常加密后能原样解回"""
        plain_text = "sk-test-only-not-a-real-key"
        cipher_text = encrypt_secret(plain_text)

        assert cipher_text
        assert cipher_text != plain_text
        assert decrypt_secret(cipher_text) == plain_text

    def test_empty_value(self):
        """空串加解密都返回空串，不产生密文"""
        assert encrypt_secret("") == ""
        assert decrypt_secret("") == ""

    def test_cipher_text_has_no_plaintext(self):
        """密文里不能出现明文片段"""
        plain_text = "sk-plaintext-must-not-leak"
        cipher_text = encrypt_secret(plain_text)

        assert plain_text not in cipher_text

    def test_same_plaintext_differs_each_time(self):
        """同一明文两次加密结果不同，但都能解回原文（随机 IV）"""
        plain_text = "sk-same-input"
        first = encrypt_secret(plain_text)
        second = encrypt_secret(plain_text)

        assert first != second
        assert decrypt_secret(first) == plain_text
        assert decrypt_secret(second) == plain_text

    @pytest.mark.parametrize(
        "cipher_text",
        [
            "not-a-valid-token",
            "gAAAAA-invalid-token",
            "",
            "中文非法密文",
        ],
    )
    def test_invalid_cipher_returns_none(self, cipher_text):
        """非法密文返回None，不抛异常（业务链路据此降级）"""
        if cipher_text == "":
            assert decrypt_secret(cipher_text) == ""
        else:
            assert decrypt_secret(cipher_text) is None

    def test_changed_jwt_secret_key_returns_none(self, monkeypatch):
        """更换 JWT_SECRET_KEY 后，历史密文解不开，返回None"""
        monkeypatch.setenv("JWT_SECRET_KEY", "first-secret-for-test")
        cipher_text = encrypt_secret("sk-key-before-rotation")

        monkeypatch.setenv("JWT_SECRET_KEY", "second-secret-for-test")
        assert decrypt_secret(cipher_text) is None

    def test_same_jwt_secret_key_is_stable(self, monkeypatch):
        """同一 JWT_SECRET_KEY 下两次加密的密文可互相解回（派生密钥稳定）"""
        monkeypatch.setenv("JWT_SECRET_KEY", "stable-secret-for-test")
        first = encrypt_secret("sk-stable-1")
        second = encrypt_secret("sk-stable-2")

        assert decrypt_secret(first) == "sk-stable-1"
        assert decrypt_secret(second) == "sk-stable-2"

    def test_missing_jwt_secret_key_still_works(self, monkeypatch):
        """JWT_SECRET_KEY 缺失时仍能加解密（降级但功能可用）"""
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        cipher_text = encrypt_secret("sk-without-jwt-secret")

        assert decrypt_secret(cipher_text) == "sk-without-jwt-secret"
