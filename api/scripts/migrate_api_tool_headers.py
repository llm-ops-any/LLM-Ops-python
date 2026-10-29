#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : migrate_api_tool_headers.py
@Desc    : 把API插件请求头里的历史明文密钥转成密文（幂等，可反复执行）

背景：CR-16102901 —— api_tool_provider.headers 原先是明文落库，
      改为密文存储后需要把存量数据转一次；已带 encrypted 标记的条目会被跳过，
      因此本脚本重复执行、或从旧备份恢复后重新执行都不会造成双重加密。

用法（容器内，先不加 --apply 看一眼要改什么）：
    docker cp api/scripts/migrate_api_tool_headers.py llmops-api:/tmp/
    docker exec llmops-api python3 /tmp/migrate_api_tool_headers.py
    docker exec llmops-api python3 /tmp/migrate_api_tool_headers.py --apply
"""
import sys

from app.http.app import app
from internal.extension.database_extension import db
from internal.lib.secret import encrypt_secret
from internal.model import ApiToolProvider


def migrate(apply: bool = False) -> None:
    """遍历所有API插件，把未加密的请求头密钥加密"""
    total_headers = 0
    total_providers = 0

    with app.app_context():
        providers = db.session.query(ApiToolProvider).all()
        print(f"共 {len(providers)} 个API插件提供者")

        for provider in providers:
            origin_headers = provider.headers or []
            new_headers = []
            changed = 0

            for header in origin_headers:
                value = (header or {}).get("value") or ""
                # 已加密或没有值的请求头原样保留
                if (header or {}).get("encrypted") or not value:
                    new_headers.append(header)
                    continue

                new_headers.append({
                    "key": header.get("key") or "",
                    "value": encrypt_secret(value),
                    "encrypted": True,
                })
                changed += 1

            if changed == 0:
                continue

            total_providers += 1
            total_headers += changed
            print(f"  [{'已处理' if apply else '待处理'}] {provider.name}: {changed} 条请求头")

            if apply:
                provider.headers = new_headers

        if apply and total_headers:
            db.session.commit()

    action = "已加密" if apply else "需要加密(未执行，加 --apply 才落库)"
    print(f"结果：{total_providers} 个插件、{total_headers} 条请求头 {action}")


if __name__ == "__main__":
    migrate(apply="--apply" in sys.argv)
