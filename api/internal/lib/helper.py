#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/7/19 17:41
@Author  : thezehui@gmail.com
@File    : helper.py
"""
import importlib
import random
import string
from datetime import datetime
from enum import Enum
from hashlib import sha3_256
from typing import Any
from uuid import UUID

from langchain_core.documents import Document
from langchain_core.pydantic_v1 import BaseModel


def dynamic_import(module_name: str, symbol_name: str) -> Any:
    """动态导入特定模块下的特定功能"""
    module = importlib.import_module(module_name)
    return getattr(module, symbol_name)


def add_attribute(attr_name: str, attr_value: Any):
    """装饰器函数，为特定的函数添加相应的属性，第一个参数为属性名字，第二个参数为属性值"""

    def decorator(func):
        setattr(func, attr_name, attr_value)
        return func

    return decorator


def generate_text_hash(text: str) -> str:
    """根据传递的文本计算对应的哈希值"""
    # 1.将需要计算哈希值的内容加上None这个字符串，避免传递了空字符串导致计算出错
    text = str(text) + "None"

    # 2.使用sha3_256将数据转换成哈希值后返回
    return sha3_256(text.encode()).hexdigest()


def datetime_to_timestamp(dt: datetime) -> int:
    """将传入的datetime时间转换成时间戳，如果数据不存在则返回0"""
    if dt is None:
        return 0
    return int(dt.timestamp())


def combine_documents(documents: list[Document]) -> str:
    """将对应的文档列表使用换行符进行合并"""
    return "\n\n".join([document.page_content for document in documents])


def build_query_with_attachments(query: str, attachments: Any = None) -> str:
    """将用户随消息上传的附件信息拼接进提问，供大模型作为上下文使用

    附件数据由前端在上传解析后携带，格式为：
    [{"name": "xxx.txt", "kind": "text|image|file", "text": "...", "url": "..."}]
    - 有text的附件注入解析出的文本；没有text的(图片/二进制)注入文件地址，便于多模态模型读取
    - 数量、单条长度、总长度都做上限保护，避免撑爆模型上下文
    - 原始提问(message.query)保持不变，附件上下文只参与本次模型调用
    """
    # 1.导入放在函数内，避免lib层与entity层出现循环引用风险
    from internal.entity.upload_file_entity import (
        MAX_CHAT_ATTACHMENT_COUNT,
        MAX_CHAT_ATTACHMENT_ONE_LENGTH,
        MAX_CHAT_ATTACHMENT_TOTAL_LENGTH,
    )

    # 2.校验附件数据是否合法，不合法直接返回原始提问
    if not isinstance(attachments, list) or len(attachments) == 0:
        return query

    # 3.循环处理附件，构建附件上下文文本
    blocks = []
    total_length = 0
    for attachment in attachments[:MAX_CHAT_ATTACHMENT_COUNT]:
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name") or "").strip() or f"附件{len(blocks) + 1}"
        kind = str(attachment.get("kind") or "text").strip()
        text = str(attachment.get("text") or "").strip()
        url = str(attachment.get("url") or "").strip()

        # 4.优先使用解析出的文本内容
        if text:
            # 4.1 单个附件超长截断
            if len(text) > MAX_CHAT_ATTACHMENT_ONE_LENGTH:
                text = text[:MAX_CHAT_ATTACHMENT_ONE_LENGTH] + "\n...(附件内容过长，已截断)"

            # 4.2 附件总长度超限则停止追加
            if total_length + len(text) > MAX_CHAT_ATTACHMENT_TOTAL_LENGTH:
                blocks.append(f"【附件{len(blocks) + 1}】{name}\n(附件内容过多，已省略)")
                break

            total_length += len(text)
            blocks.append(f"【附件{len(blocks) + 1}】{name}\n{text}")
        elif url:
            # 5.没有文本(图片/二进制文件)时注入文件地址，为多模态模型预留
            kind_label = {"image": "图片", "file": "文件"}.get(kind, "文件")
            blocks.append(
                f"【附件{len(blocks) + 1}】{name}（{kind_label}）\n文件地址：{url}"
            )

    # 6.没有有效附件内容则直接返回原始提问
    if not blocks:
        return query

    return (
        f"{query}\n\n"
        "-----\n"
        f"用户随本条消息上传了{len(blocks)}个附件，以下为附件信息(文本内容或文件地址)，"
        "请结合附件信息回答用户提问：\n\n"
        + "\n\n".join(blocks)
        + "\n-----"
    )


def is_model_image_attachment(attachment: Any) -> bool:
    """判断附件是否可以交给多模态模型直接看图

    说明(CR-16102701 / FR-01)：只有「kind=image + 没解析出文本 + http(s)地址」的附件才按图片传入。
    - 有text的图片继续走文本注入，避免同一份内容既进文本又进图片；
    - data:/本地路径这类地址模型侧拉不到，退回文本，不让模型收到一个取不回的图片引用。
    """
    if not isinstance(attachment, dict):
        return False
    if str(attachment.get("kind") or "").strip() != "image":
        return False
    if str(attachment.get("text") or "").strip():
        return False
    url = str(attachment.get("url") or "").strip().lower()
    return url.startswith("http://") or url.startswith("https://")


def extract_message_text(content: Any) -> str:
    """把消息content归一化成纯文本

    说明(CR-16102701 / FR-04)：视觉模型的消息内容是list(多模态)，而输入审核用的是
    `keyword in content`——对list而言是元素比较，永远判不中，等于审核被静默绕过。
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                texts.append(str(item.get("text") or ""))
        return "\n".join(text for text in texts if text)
    return "" if content is None else str(content)


def build_human_message_content(
        query: str,
        attachments: Any = None,
        supports_image: bool = False,
) -> Any:
    """构造本轮人类消息内容：模型支持图片输入时返回多模态list，否则返回纯文本

    说明(CR-16102701 / FR-01、FR-02)：
    - supports_image 由调用方按 ModelFeature.IMAGE_INPUT 判定，这里不猜模型能力。
      实测非视觉模型(deepseek-flash)收到多模态内容会**静默返回空**而不是报错，猜错的代价是用户拿不到任何回答。
    - 为假或无图片附件时逐字退回 build_query_with_attachments，保证非视觉模型零回归。
    - 文本类附件仍交给既有拼装处理，截断与上限规则只保留一处。
    """
    # 1.不支持图片输入、没有附件，直接按改造前的方式构造纯文本
    if not supports_image or not isinstance(attachments, list) or len(attachments) == 0:
        return build_query_with_attachments(query, attachments)

    # 2.拆出可直传的图片与其它附件
    from internal.entity.upload_file_entity import MAX_CHAT_ATTACHMENT_COUNT

    images: list[tuple[str, str]] = []
    others: list[Any] = []
    for attachment in attachments[:MAX_CHAT_ATTACHMENT_COUNT]:
        if is_model_image_attachment(attachment):
            name = str(attachment.get("name") or "").strip() or f"图片{len(images) + 1}"
            images.append((name, str(attachment.get("url") or "").strip()))
        else:
            others.append(attachment)

    # 3.没有可直传的图片则退回纯文本
    if not images:
        return build_query_with_attachments(query, attachments)

    # 4.文本段：提问 + 图片清单 + 其它附件
    sections = [
        str(query or ""),
        "-----",
        f"用户随本条消息上传了{len(images)}张图片（顺序与下方图片一致），请结合图片回答用户提问：",
        "\n".join(f"【图片{index}】{name}" for index, (name, _) in enumerate(images, start=1)),
    ]
    if others:
        sections.append(build_query_with_attachments("", others).strip())

    # 5.组装多模态内容：文本在前，图片按上传顺序在后
    content = [{"type": "text", "text": "\n\n".join(section for section in sections if section)}]
    content.extend(
        {"type": "image_url", "image_url": {"url": url}} for _, url in images
    )
    return content


def build_attachment_metadata(attachments: Any = None, text_limit: int = 4000) -> list[dict]:
    """将前端上传的附件精简成可入库的元信息列表

    说明：
    - 附件解析出的文本可能非常长(单文件最大30MB)，直接入库会让message表迅速膨胀，
      因此文本只保留前text_limit个字符，足够历史消息展示与后续轮次引用
    - 图片与二进制附件保留对象存储地址(url)，刷新页面后依然可以直接预览/下载
    """
    # 1.校验附件数据是否合法
    if not isinstance(attachments, list) or len(attachments) == 0:
        return []

    # 2.导入放在函数内，避免lib层与entity层出现循环引用风险
    from internal.entity.upload_file_entity import MAX_CHAT_ATTACHMENT_COUNT

    # 3.循环精简每个附件的字段
    metadata = []
    for attachment in attachments[:MAX_CHAT_ATTACHMENT_COUNT]:
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name") or "").strip()
        text = str(attachment.get("text") or "").strip()
        url = str(attachment.get("url") or "").strip()
        if not name or (not text and not url):
            continue

        # 3.1 体积字段做安全转换，避免脏数据导致写入失败
        try:
            size = int(attachment.get("size") or 0)
        except (TypeError, ValueError):
            size = 0

        metadata.append({
            "name": name,
            "extension": str(attachment.get("extension") or "").strip(),
            "size": size,
            "kind": str(attachment.get("kind") or ("text" if text else "file")).strip(),
            "mime": str(attachment.get("mime") or "").strip(),
            "url": url,
            "text": text[:text_limit],
            "truncated": bool(attachment.get("truncated")) or len(text) > text_limit,
            "note": str(attachment.get("note") or "").strip(),
        })

    return metadata


def dump_attachment_metadata(attachments: Any = None) -> list[dict]:
    """将消息中持久化的附件元信息转换成响应数据

    说明：历史消息列表不需要附件正文，剔除text字段避免返回大字段拖慢分页接口
    """
    if not isinstance(attachments, list):
        return []

    return [
        {key: value for key, value in attachment.items() if key != "text"}
        for attachment in attachments
        if isinstance(attachment, dict)
    ]


def remove_fields(data_dict: dict, fields: list[str]) -> None:
    """根据传递的字段名移除字典中指定的字段"""
    for field in fields:
        data_dict.pop(field, None)


def convert_model_to_dict(obj: Any, *args, **kwargs):
    """辅助函数，将Pydantic V1版本中的UUID/Enum等数据转换成可序列化存储的数据。"""
    # 1.如果是Pydantic的BaseModel类型，递归处理其字段
    if isinstance(obj, BaseModel):
        obj_dict = obj.dict(*args, **kwargs)
        # 2.递归处理嵌套字段
        for key, value in obj_dict.items():
            obj_dict[key] = convert_model_to_dict(value, *args, **kwargs)
        return obj_dict

    # 3.如果是 UUID 类型，转换为字符串
    elif isinstance(obj, UUID):
        return str(obj)

    # 4.如果是 Enum 类型，转换为其值
    elif isinstance(obj, Enum):
        return obj.value

    # 5.如果是列表类型，递归处理列表中的每个元素
    elif isinstance(obj, list):
        return [convert_model_to_dict(item, *args, **kwargs) for item in obj]

    # 6.如果是字典类型，递归处理字典中的每个字段
    elif isinstance(obj, dict):
        return {key: convert_model_to_dict(value, *args, **kwargs) for key, value in obj.items()}

    # 7.对其他类型的字段，保持原样
    return obj


def get_value_type(value: Any) -> Any:
    """根据传递的值获取变量的类型，并将str和bool转换成string和boolean"""
    # 1.计算变量的类型并转换成字符串
    value_type = type(value).__name__

    # 2.判断是否为str或者是bool
    if value_type == "str":
        return "string"
    elif value_type == "bool":
        return "boolean"

    return value_type


def generate_random_string(length: int = 16) -> str:
    """根据传递的位数，生成随机字符串"""
    # 1.定义字符集，包含大小写字母和数字
    chars = string.ascii_letters + string.digits

    # 2.使用random.choices生成指定长度的随机字符串
    random_str = ''.join(random.choices(chars, k=length))

    return random_str
