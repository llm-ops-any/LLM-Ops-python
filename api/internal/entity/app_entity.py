#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/10/29 11:04
@Author  : thezehui@gmail.com
@File    : app_entity.py
"""
from enum import Enum

# 内置应用图标清单（SVG文件位于 ui/public/app-icons，构建后通过 /app-icons/ 静态访问）
# 说明：本项目所在的中转平台没有可用的图片生成模型（dall-e-3 报503 model_not_found，
#      gpt-image-2 走 /v1/images/generations 报 Invalid task protocol request），
#      因此自动创建应用时不再调用AI绘画接口，改为从内置图标中挑选，零外部依赖且不会失败。
#      原「AI生图」用的提示词(GENERATE_ICON_PROMPT_TEMPLATE)未删除，已移至
#      internal/entity/image_prompt_entity.py 预留，启用方式见该文件。
# 注意：本清单需与 ui/src/components/IconPicker.vue 中的 builtinIcons 保持同步。
BUILTIN_APP_ICONS = {
    "robot": "/app-icons/robot.svg",
    "chat": "/app-icons/chat.svg",
    "folder": "/app-icons/folder.svg",
    "code": "/app-icons/code.svg",
    "chart": "/app-icons/chart.svg",
    "bolt": "/app-icons/bolt.svg",
    "star": "/app-icons/star.svg",
    "globe": "/app-icons/globe.svg",
    "music": "/app-icons/music.svg",
    "camera": "/app-icons/camera.svg",
    "rocket": "/app-icons/rocket.svg",
    "shield": "/app-icons/shield.svg",
    "gear": "/app-icons/gear.svg",
    "cloud": "/app-icons/cloud.svg",
    "heart": "/app-icons/heart.svg",
    "leaf": "/app-icons/leaf.svg",
    "bag": "/app-icons/bag.svg",
    "crown": "/app-icons/crown.svg",
    "coffee": "/app-icons/coffee.svg",
    "compass": "/app-icons/compass.svg",
    "flask": "/app-icons/flask.svg",
    "bulb": "/app-icons/bulb.svg",
    "clock": "/app-icons/clock.svg",
    "pencil": "/app-icons/pencil.svg",
}

# 自动创建应用时使用的兜底图标（模型未能选出有效图标时使用）
DEFAULT_APP_ICON = BUILTIN_APP_ICONS["robot"]

# 挑选内置图标的提示词模板
SELECT_ICON_PROMPT_TEMPLATE = """你是一个应用图标选择助手，请根据用户传递的`应用名称`和`应用描述`，从候选图标中挑选最贴切的一个。

候选图标（图标名称: 适用场景）:
robot: 机器人、智能体、通用助手
chat: 对话、问答、客服、咨询
folder: 文档、资料、知识管理
code: 编程、开发、代码审查
chart: 数据分析、报表、统计
bolt: 效率、性能、批处理、加速
star: 推荐、评价、精选
globe: 翻译、国际化、旅游、地理
music: 音乐、音频、配音
camera: 图像、视觉、识别
rocket: 发布、增长、创业、营销
shield: 安全、风控、内容审核
gear: 配置、运维、系统工具
cloud: 云服务、存储、同步
heart: 情感、健康、心理、关怀
leaf: 环保、农业、生活方式
bag: 电商、购物、交易
crown: 会员、VIP、用户运营
coffee: 餐饮、休闲、社交
compass: 出行、导航、探索
flask: 实验、科研、测试
bulb: 创意、灵感、头脑风暴
clock: 日程、提醒、时间管理
pencil: 写作、文案、编辑

用户传递的数据如下:
应用名称: {name}。
应用描述: {description}。

只返回一个图标名称（例如 robot），不要返回其他任何内容"""


class AppStatus(str, Enum):
    """应用状态枚举类"""
    DRAFT = "draft"
    PUBLISHED = "published"


class AppConfigType(str, Enum):
    """应用配置类型枚举类"""
    DRAFT = "draft"
    PUBLISHED = "published"


# 应用默认配置信息
DEFAULT_APP_CONFIG = {
    "model_config": {
        # 说明：本项目的模型统一走uino中转平台(地址由docker/.env的OPENAI_API_BASE注入)。
        #      原值为openai/gpt-4o-mini：因为本地注册了openai/gpt-4o-mini.yaml，加载不会报错，
        #      但调用时平台会返回503 model_not_found，导致新建应用的对话直接失败。
        "provider": "uino",
        "model": "deepseek-v4-flash",
        "parameters": {
            "temperature": 0.5,
            "top_p": 0.85,
            "frequency_penalty": 0.2,
            "presence_penalty": 0.2,
            "max_tokens": 8192,
        },
    },
    "dialog_round": 3,
    "preset_prompt": "",
    "tools": [],
    "workflows": [],
    "datasets": [],
    "retrieval_config": {
        "retrieval_strategy": "semantic",
        "k": 10,
        "score": 0.5,
    },
    "long_term_memory": {
        "enable": False,
    },
    "opening_statement": "",
    "opening_questions": [],
    "speech_to_text": {
        "enable": False,
    },
    "text_to_speech": {
        "enable": False,
        "voice": "echo",
        "auto_play": False,
    },
    "suggested_after_answer": {
        "enable": True,
    },
    "review_config": {
        "enable": False,
        "keywords": [],
        "inputs_config": {
            "enable": False,
            "preset_response": "",
        },
        "outputs_config": {
            "enable": False,
        },
    },
}
