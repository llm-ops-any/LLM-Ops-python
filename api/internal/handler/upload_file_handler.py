#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/8/12 10:36
@Author  : thezehui@gmail.com
@File    : upload_file_handler.py
"""
from dataclasses import dataclass

from flask_login import login_required, current_user
from injector import inject

from internal.service import CosService
from internal.core.file_extractor import AttachmentTextExtractor
from internal.entity.upload_file_entity import (
    ALLOWED_IMAGE_EXTENSION,
    MAX_CHAT_ATTACHMENT_TEXT_LENGTH,
)
from internal.exception import FailException
from internal.schema.upload_file_schema import (
    UploadAttachmentReq,
    UploadFileReq,
    UploadFileResp,
    UploadImageReq,
)
from pkg.response import validate_error_json, success_json


@inject
@dataclass
class UploadFileHandler:
    """上传文件处理器"""
    cos_service: CosService

    @login_required
    def upload_file(self):
        """上传文件/文档"""
        # 1.构建请求并校验
        req = UploadFileReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务上传文件并获取记录
        upload_file = self.cos_service.upload_file(req.file.data, False, current_user)

        # 3.构建响应并返回
        resp = UploadFileResp()
        return success_json(resp.dump(upload_file))

    @login_required
    def upload_image(self):
        """上传图片"""
        # 1.构建请求并校验
        req = UploadImageReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.调用服务并上传文件
        upload_file = self.cos_service.upload_file(req.file.data, True, current_user)

        # 3.获取图片的实际URL地址
        image_url = self.cos_service.get_file_url(upload_file.key)

        return success_json({"image_url": image_url})

    @login_required
    def upload_attachment(self):
        """上传对话附件：能解析出文本的返回文本，图片与其它二进制文件上传对象存储并返回URL

        返回结构中的kind用于区分附件类型：
        - text：已解析出文本(随消息注入上下文)
        - image：图片，返回可访问的url(供多模态视觉模型直接使用)
        - file：其它二进制文件(音视频/压缩包/老格式文档等)，返回可访问的url
        """
        # 1.构建请求并校验
        req = UploadAttachmentReq()
        if not req.validate():
            return validate_error_json(req.errors)

        # 2.读取附件基础信息与内容
        file = req.file.data
        name = file.filename or ""
        extension = AttachmentTextExtractor.get_extension(name)
        content = file.stream.read()
        kind, text, truncated, url, note = "text", "", False, "", ""

        # 3.能解析文本的类型先走文本解析，解析失败则降级为对象存储附件
        if AttachmentTextExtractor.is_parseable(name):
            try:
                text = AttachmentTextExtractor.extract(name, content)
                truncated = len(text) > MAX_CHAT_ATTACHMENT_TEXT_LENGTH
                if truncated:
                    text = text[:MAX_CHAT_ATTACHMENT_TEXT_LENGTH]
            except FailException as e:
                text, note = "", e.message or "附件文本解析失败"

        # 4.没有文本(图片/二进制/解析失败)则上传对象存储，返回可访问URL
        if not text:
            kind = "image" if extension in ALLOWED_IMAGE_EXTENSION else "file"
            file.stream.seek(0)
            upload_file = self.cos_service.upload_file(
                file,
                kind == "image",
                current_user,
                allow_any_extension=True,
            )
            url = self.cos_service.get_file_url(upload_file.key)
            if not note:
                note = (
                    "图片已上传，服务端未解析出文本内容，可使用其文件地址进行视觉理解"
                    if kind == "image"
                    else "该文件已上传，服务端未解析出文本内容，仅提供文件地址"
                )

        # 5.构建响应并返回
        return success_json({
            "name": name,
            "extension": extension,
            "size": len(content),
            "mime": file.mimetype,
            "kind": kind,
            "text": text,
            "url": url,
            "truncated": truncated,
            "note": note,
        })
