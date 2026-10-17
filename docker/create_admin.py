#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
创建 LLMOps 初始管理员账号。

背景：本项目没有「注册」接口，账号只在 GitHub OAuth 授权时自动创建。
     因此未配置 GitHub OAuth 的环境（内网 / 自建服务器）必须手工建一个账号才能登录。

用法（在 docker/ 目录下执行，脚本会被复制进 llmops-api 容器运行）：

    docker compose cp create_admin.py llmops-api:/tmp/create_admin.py
    docker compose exec llmops-api python /tmp/create_admin.py <email> <password>

示例：

    docker compose exec llmops-api python /tmp/create_admin.py admin@llmops.local Llmops@2026

密码规则：8-16 位，至少包含一个字母和一个数字。
"""
import os
import re
import sys

# 容器内的项目根目录（Dockerfile WORKDIR 为 /app/api），确保能 import pkg / app 等模块
sys.path.insert(0, os.getcwd())

import base64
import binascii
import hashlib
import secrets

from pkg.password import hash_password

# 与 pkg/password 一致：8-16 位，含字母与数字
PASSWORD_PATTERN = r"^(?=.*[a-zA-Z])(?=.*\d).{8,16}$"


def main():
    if len(sys.argv) != 3:
        print("用法: python create_admin.py <email> <password>")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    if re.match(PASSWORD_PATTERN, password) is None:
        print("密码规则校验失败：需 8-16 位，且至少包含一个字母和一个数字")
        sys.exit(1)

    # 延迟导入：确保先完成参数校验，再加载 Flask 应用
    from sqlalchemy import text
    from app.http.app import app
    from internal.extension.database_extension import db

    salt = secrets.token_bytes(16)
    # 与 AccountService.update_password 完全一致的存储格式
    password_hashed = base64.b64encode(hash_password(password, salt)).decode()
    password_salt = base64.b64encode(salt).decode()

    with app.app_context():
        exists = db.session.execute(
            text("SELECT id FROM account WHERE email = :email"),
            {"email": email},
        ).first()

        if exists:
            print(f"账号已存在，跳过创建：{email}")
            return

        db.session.execute(
            text("""
                INSERT INTO account (name, email, avatar, password, password_salt, last_login_ip)
                VALUES (:name, :email, '', :password, :password_salt, '127.0.0.1')
            """),
            {
                "name": email.split("@")[0],
                "email": email,
                "password": password_hashed,
                "password_salt": password_salt,
            },
        )
        db.session.commit()

    print(f"已创建账号 => 邮箱: {email}  密码: {password}")
    print("请登录后立即在「账号设置」中修改密码。")


if __name__ == "__main__":
    main()
