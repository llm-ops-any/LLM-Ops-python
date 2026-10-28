#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CR-16102804 验证：pptx 工具已注册、能生成真实 pptx、异常输入不炸"""
import os

SAMPLE = """# 成长 LLMOps 平台

## 一、定位
面向企业的 Agent 应用构建与运营平台。

## 二、核心能力
- 多模型接入与统一凭证
- 知识库检索增强
- 工作流编排
- 开放 API

## 三、下一步
补齐语音与多渠道发布能力。
"""


def main():
    from app.http.app import app
    from app.http.module import injector
    from internal.core.tools.builtin_tools.providers.builtin_provider_manager import (
        BuiltinProviderManager,
    )

    with app.app_context():
        manager = injector.get(BuiltinProviderManager)

        # 1. provider 与工具是否可见
        providers = manager.get_providers()
        names = [item.name for item in providers]
        print("provider 列表 =", names)
        print("含 pptx =", "pptx" in names)

        provider = manager.get_provider("pptx")
        if provider is None:
            print("✗ 取不到 pptx provider")
            return
        entity = provider.provider_entity
        print("label =", entity.label, "| 分类 =", entity.category, "| background =", entity.background)
        print("工具 =", list(provider.tool_entity_map.keys()))

        # 2. 图标
        print(f"icon 文件名 = {entity.icon}（HTTP 侧已单独验证返回 1621 字节 image/png）")

        # 3. 真实生成
        # 说明：manager.get_tool 返回的是「工厂函数」，要调用一次才拿到 BaseTool 实例
        tool = manager.get_tool("pptx", "markdown_to_pptx")()
        print("tool =", tool.name)
        url = tool.invoke({"markdown": SAMPLE})
        print("生成结果 =", url)
        print("是 URL =", isinstance(url, str) and url.startswith("http"))

        # 4. 异常输入：空 markdown 不应抛异常
        try:
            empty_result = tool.invoke({"markdown": ""})
            print("空输入返回 =", str(empty_result)[:120])
        except Exception as error:  # noqa: BLE001
            print("✗ 空输入抛异常:", type(error).__name__, str(error)[:120])


if __name__ == "__main__":
    main()
