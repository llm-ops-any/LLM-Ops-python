#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2026/10/16
@Author  : thezehui@gmail.com
@File    : image_prompt_entity.py
"""
# ============================================================================
# AI 生图提示词 · 预留区（当前未接入任何业务流程，请勿当成死代码删除）
# ============================================================================
# 背景：本项目所在的中转平台目前没有任何可用的图片生成能力，2026-10-16 实测：
#   1) dall-e-3 走 /v1/images/generations 报 503 model_not_found（该分组下无可用渠道）；
#   2) gpt-image-2 是平台上唯一的图片模型，但不兼容该接口的标准协议——最小请求体
#      （仅 model + prompt）即报 Invalid task protocol request，分别加上 size / quality /
#      response_format=b64_json / n 后同样如此。
#   因此 app_service.auto_create_app 改为从内置图标(BUILTIN_APP_ICONS，见 app_entity.py)
#   中挑选，不再调用 AI 绘画。
#
# 为什么仍然保留：下面的提示词负责把「应用名称 + 应用描述」翻译成绘画模型可用的英文描述，
#   是整条生图链路的入口。等平台开放了可用渠道、或更换为其他图片模型（通义万相 / 即梦等）时
#   要直接复用，故从 app_entity.py 中移出、单独存放于此。
#
# 启用方式：在 app_service.auto_create_app 里把下面这条链接回 llm 即可——
#       generate_icon_chain = ChatPromptTemplate.from_template(
#           GENERATE_ICON_PROMPT_TEMPLATE
#       ) | llm | StrOutputParser() | dalle_api_wrapper.run
# 两个必须注意的点：
#   1) 必须保留「生成失败 → 回退 DEFAULT_APP_ICON」的兜底，否则会重演
#      "前端提示创建成功、应用实际没建出来"的故障；
#   2) DALL-E 返回的是临时 URL，要持久化需先下载再上传对象存储（原实现的
#      requests.get + cos_service.upload_file 已随本次改造移除，按需恢复）。

# 生成icon描述提示词模板
GENERATE_ICON_PROMPT_TEMPLATE = """你是一个拥有10年经验的AI绘画工程师，可以将用户传递的`应用名称`和`应用描述`转换为对应应用的icon描述。
该描述主要用于DallE AI绘画，并且该描述是英文，用户传递的数据如下:

应用名称: {name}。
应用描述: {description}。

并且除了icon描述提示词外，其他什么都不要生成"""
