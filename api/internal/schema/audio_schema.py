#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : audio_schema.py
@Desc    : 语音服务配置与语音接口的请求/响应结构（CR-16102803）
"""
from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired, FileSize
from marshmallow import Schema, fields
from wtforms import StringField
from wtforms.validators import DataRequired, Length, Optional

from internal.entity.audio_entity import (
    COSYVOICE_VOICE_OPTIONS,
    OMNI_VOICE_OPTIONS,
    AudioEngine,
)

# 引擎的展示名称（前端下拉直接用，避免前后端各写一份文案）
ENGINE_LABELS = {
    AudioEngine.BROWSER.value: "浏览器（Web Speech + 系统朗读）",
    AudioEngine.OMNI.value: "Qwen-Omni-Realtime（实时多模态）",
    AudioEngine.DASHSCOPE.value: "CosyVoice + Paraformer（专用语音）",
}


class GetSpeechProviderResp(Schema):
    """语音服务配置响应结构，不含任何密钥明文"""
    engine = fields.String(dump_default=AudioEngine.BROWSER.value)
    has_api_key = fields.Boolean(dump_default=False)
    masked_api_key = fields.String(dump_default="")
    omni_model = fields.String(dump_default="")
    omni_voice = fields.String(dump_default="")
    omni_host = fields.String(dump_default="")
    cosyvoice_model = fields.String(dump_default="")
    cosyvoice_voice = fields.String(dump_default="")
    paraformer_model = fields.String(dump_default="")
    source = fields.String(dump_default="")
    source_label = fields.String(dump_default="")
    engines = fields.Method("get_engines", dump_default=[])
    omni_voice_options = fields.List(fields.String(), dump_default=OMNI_VOICE_OPTIONS)
    cosyvoice_voice_options = fields.List(fields.String(), dump_default=COSYVOICE_VOICE_OPTIONS)

    def get_engines(self, _data) -> list:
        """引擎候选：value + 中文名，供前端渲染下拉"""
        return [{"value": value, "label": label} for value, label in ENGINE_LABELS.items()]


class UpdateSpeechProviderReq(FlaskForm):
    """更新语音服务配置请求结构（所有字段可选，只传要改的）"""
    engine = StringField(
        "engine",
        default="",
        validators=[Optional(), Length(max=32, message="引擎名称长度不能超过32个字符")],
    )
    dashscope_api_key = StringField(
        "dashscope_api_key",
        default="",
        validators=[Optional(), Length(max=512, message="API Key长度不能超过512个字符")],
    )
    omni_model = StringField("omni_model", default="", validators=[Optional(), Length(max=128)])
    omni_voice = StringField("omni_voice", default="", validators=[Optional(), Length(max=64)])
    omni_host = StringField("omni_host", default="", validators=[Optional(), Length(max=255)])
    cosyvoice_model = StringField("cosyvoice_model", default="", validators=[Optional(), Length(max=128)])
    cosyvoice_voice = StringField("cosyvoice_voice", default="", validators=[Optional(), Length(max=64)])
    paraformer_model = StringField("paraformer_model", default="", validators=[Optional(), Length(max=128)])

    def validate_engine(self, field: StringField) -> bool:
        """引擎必须是三档之一，否则给出明确提示"""
        if not field.data:
            return True
        if field.data not in {item.value for item in AudioEngine}:
            raise ValueError("语音引擎不支持，可选值：browser / omni / dashscope")
        return True


class AudioToTextReq(FlaskForm):
    """语音转文本请求结构

    说明：仅 dashscope 引擎走服务端识别；上限 25MB 与前端 MediaRecorder 的产出量级匹配。
    """
    file = FileField(
        "file",
        validators=[
            FileRequired(message="转换音频文件不能为空"),
            FileSize(max_size=25 * 1024 * 1024, message="音频文件不能超过25MB"),
            FileAllowed(["webm", "wav", "mp3", "ogg", "m4a"], message="请上传正确的音频文件"),
        ],
    )


class MessageToAudioReq(FlaskForm):
    """消息转语音请求结构"""
    message_id = StringField("message_id", validators=[DataRequired(message="消息id不能为空")])
