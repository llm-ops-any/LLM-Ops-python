#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : audio_handler.py
@Desc    : 语音能力的控制器（CR-16102803）：配置读写 / 连通性测试 / 语音转文本 / 消息转语音
"""
from dataclasses import dataclass
from uuid import UUID

from flask_login import current_user, login_required
from injector import inject

from internal.schema.audio_schema import (
    AudioToTextReq,
    GetSpeechProviderResp,
    MessageToAudioReq,
    UpdateSpeechProviderReq,
)
from internal.service import AudioService, SpeechProviderService
from pkg.response import compact_generate_response, success_json, validate_error_json


@inject
@dataclass
class AudioHandler:
    """语音能力处理器"""
    audio_service: AudioService
    speech_provider_service: SpeechProviderService

    # ---------------------------------------------------------------- 配置

    @login_required
    def get_speech_provider(self):
        """读取语音服务配置（密钥只返回固定掩码，AC-01）"""
        resp = GetSpeechProviderResp()
        return success_json(resp.dump(self.speech_provider_service.get_masked_setting()))

    @login_required
    def update_speech_provider(self):
        """保存语音服务配置，dashscope_api_key 为空表示不修改已存密钥

        说明：只传 engine 也能保存，未传的模型字段保持原值（见 save_config）。
        """
        req = UpdateSpeechProviderReq()
        if not req.validate():
            return validate_error_json(req.errors)

        self.speech_provider_service.save_config(
            engine=req.engine.data,
            dashscope_api_key=req.dashscope_api_key.data,
            omni_model=req.omni_model.data,
            omni_voice=req.omni_voice.data,
            omni_host=req.omni_host.data,
            cosyvoice_model=req.cosyvoice_model.data,
            cosyvoice_voice=req.cosyvoice_voice.data,
            paraformer_model=req.paraformer_model.data,
        )
        resp = GetSpeechProviderResp()
        return success_json(resp.dump(self.speech_provider_service.get_masked_setting()))

    @login_required
    def test_speech_provider(self):
        """测试当前引擎是否真的能出声（不落库、不改配置）"""
        return success_json(self.speech_provider_service.test_connection())

    # ---------------------------------------------------------------- 语音

    @login_required
    def audio_to_text(self):
        """把上传的音频转换成文本（仅 dashscope 引擎走服务端）"""
        req = AudioToTextReq()
        if not req.validate():
            return validate_error_json(req.errors)

        file = req.file.data
        text = self.audio_service.audio_to_text(file.stream.read(), file.filename or "recording.wav")
        return success_json({"text": text})

    @login_required
    def message_to_audio(self):
        """把消息答案转换成流式语音（SSE）"""
        req = MessageToAudioReq()
        if not req.validate():
            return validate_error_json(req.errors)

        response = self.audio_service.message_to_audio(UUID(req.message_id.data), current_user)
        return compact_generate_response(response)
