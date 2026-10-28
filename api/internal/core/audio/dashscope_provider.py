#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : dashscope_provider.py
@Desc    : 专用语音引擎（CosyVoice TTS + Paraformer ASR），CR-16102803 / D-06

关键实测结论（前置资源 P-04 / P-05）：
1. cosyvoice-v3.5-flash 在 PO 账号上 0 字节静默失败（418），v3-flash 正常 ⇒ 默认 v3-flash，模型名可配；
2. SDK 失败时可能既不抛异常也不返回音频 ⇒ **必须判空**，否则前端表现为「点了没声音也没报错」；
3. paraformer-realtime-v2 是**流式回调**接口（需 callback + start/send_audio_frame/stop），
   没有 `call(file=)` 这种用法；且**不支持 webm 容器**，所以前端录音必须是 WAV。
"""
import base64
import io
import logging
import queue
import threading
import time
import wave
from typing import Generator

from internal.entity.audio_entity import (
    ASR_TOTAL_TIMEOUT,
    AUDIO_SAMPLE_RATE,
    TTS_CHUNK_TIMEOUT,
    TTS_TOTAL_TIMEOUT,
)
from internal.exception import FailException
from .base import BaseAudioProvider

# ASR 采样率固定 16k（Paraformer 要求），与 TTS 的 24k 下行不同
ASR_SAMPLE_RATE = 16000
# 每次 send_audio_frame 的字节数（16k/16bit/单声道 ≈ 0.1 秒）
ASR_FRAME_BYTES = 3200


class DashScopeProvider(BaseAudioProvider):
    """CosyVoice + Paraformer provider"""
    name = "dashscope"
    supports_tts = True
    supports_asr = True

    def __init__(self, config) -> None:
        self.config = config

    # ---------------------------------------------------------------- 公共

    def _prepare(self) -> None:
        """校验 Key 并注入 dashscope，缺 Key 时给可读提示（AC-07）"""
        if not self.config.has_api_key:
            raise FailException("语音服务未配置，请在「设置 → 语音服务」填写阿里百炼 API Key")

        import dashscope

        dashscope.api_key = self.config.api_key

    # ---------------------------------------------------------------- TTS

    def _create_synthesizer(self, callback=None):
        """创建合成器，统一请求 PCM 24k（与 Omni 对齐，D-05）"""
        from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

        kwargs = {
            "model": (self.config.cosyvoice_model or "cosyvoice-v3-flash").strip(),
            "voice": (self.config.cosyvoice_voice or "longxiaochun_v3").strip(),
            # 与 Omni 同为 24k PCM，前端只需一套播放器
            "format": AudioFormat.PCM_24000HZ_MONO_16BIT,
        }
        if callback is not None:
            kwargs["callback"] = callback
        return SpeechSynthesizer(**kwargs)

    def tts_stream(self, text: str) -> Generator[dict, None, None]:
        """流式合成：后台线程推 SDK，主线程从队列取块转 SSE"""
        self._prepare()

        from dashscope.audio.tts_v2 import ResultCallback

        chunks: "queue.Queue[tuple]" = queue.Queue()

        class _Callback(ResultCallback):
            """把 SDK 的回调转成队列事件，跨线程交给生成器"""

            def on_open(self) -> None:
                return None

            def on_data(self, data: bytes) -> None:
                if data:
                    chunks.put(("data", data))

            def on_complete(self) -> None:
                chunks.put(("complete", None))

            def on_error(self, message) -> None:
                chunks.put(("error", str(message)))

            def on_close(self) -> None:
                chunks.put(("close", None))

        try:
            synthesizer = self._create_synthesizer(callback=_Callback())
        except Exception as error:
            logging.error("创建 CosyVoice 合成器失败: %s", error, exc_info=True)
            raise FailException("语音合成失败（合成器初始化异常），请检查模型与音色配置") from error

        def _worker() -> None:
            """在后台完成「送文本 -> 等结束」，异常也走队列，避免主线程卡死"""
            try:
                synthesizer.streaming_call(text)
                synthesizer.streaming_complete()
            except Exception as error:  # noqa: BLE001 - 统一转业务错误
                chunks.put(("error", f"{type(error).__name__}: {error}"))
            finally:
                chunks.put(("end", None))

        threading.Thread(target=_worker, name="cosyvoice-tts", daemon=True).start()

        started = time.monotonic()
        received = 0
        while True:
            remaining = TTS_TOTAL_TIMEOUT - (time.monotonic() - started)
            if remaining <= 0:
                raise FailException("语音合成超时，请稍后重试（文本过长可先缩短）")
            try:
                kind, payload = chunks.get(timeout=min(TTS_CHUNK_TIMEOUT, remaining))
            except queue.Empty:
                raise FailException("语音合成超时，未收到音频数据，请稍后重试")

            if kind == "data":
                received += len(payload)
                yield {
                    "audio": base64.b64encode(payload).decode("utf-8"),
                    "sample_rate": AUDIO_SAMPLE_RATE,
                }
            elif kind == "error":
                # 说明：418 这类错误 SDK 只会打日志、返回空音频，这里兜住并转成可读提示
                logging.error("CosyVoice 合成失败: %s", payload)
                raise FailException("语音合成失败（模型或音色不可用），请检查语音服务配置")
            elif kind == "end":
                break

        # 零音频 = 失败（P-04 的 v3.5 就是这种表现，不能当成功）
        if received == 0:
            raise FailException("语音合成失败（未返回音频），请检查 CosyVoice 模型与音色是否可用")

    # ---------------------------------------------------------------- ASR

    @staticmethod
    def _to_pcm_frames(content: bytes, filename: str) -> tuple:
        """把上传的音频拆成 16k PCM 帧，返回 (帧列表, 是否 wav)

        Paraformer 只吃裸 PCM 帧；wav 需要先跳过容器头，否则会把头当成噪音。
        其他格式（webm/mp3）本 SDK 版本无法解析，直接给明确提示。
        """
        lowered = (filename or "").lower()
        if lowered.endswith(".wav"):
            try:
                with wave.open(io.BytesIO(content), "rb") as handle:
                    if handle.getframerate() != ASR_SAMPLE_RATE or handle.getnchannels() != 1:
                        raise FailException(
                            f"音频必须是 {ASR_SAMPLE_RATE}Hz 单声道 WAV，当前为 "
                            f"{handle.getframerate()}Hz/{handle.getnchannels()}声道"
                        )
                    raw = handle.readframes(handle.getnframes())
            except FailException:
                raise
            except Exception as error:
                raise FailException("音频文件解析失败，请重新录制") from error
            is_wav = True
        else:
            # 裸 PCM 兜底（前端若已自行去头可直接传）
            raw = content
            is_wav = False

        if not raw:
            raise FailException("音频内容为空，请重新录制")

        return [raw[index:index + ASR_FRAME_BYTES] for index in range(0, len(raw), ASR_FRAME_BYTES)], is_wav

    def asr(self, content: bytes, filename: str) -> str:
        """流式回调识别：边送帧边收句子，结束后拼成完整文本"""
        self._prepare()

        from dashscope.audio.asr import Recognition, RecognitionCallback

        frames, _ = self._to_pcm_frames(content, filename)

        sentences: list = []
        partial: list = []
        errors: list = []
        finished = threading.Event()

        class _Callback(RecognitionCallback):
            """收集识别句子；任何回调都可能在工作线程里触发

            说明：识别是增量的，同一个句子会多次回调「部分结果」。
                 只累计 sentence_end=True 的完整句，否则会出现
                 「今天的今天的今天的…」这种重复叠加（2026-10-28 实测踩到）。
            """

            def on_open(self) -> None:
                return None

            def on_event(self, result) -> None:
                try:
                    sentence = result.get_sentence()
                except Exception:  # 兼容不同版本的返回结构
                    sentence = None
                if not sentence:
                    return
                text = (sentence.get("text") or "").strip()
                if not text:
                    return
                if sentence.get("sentence_end") is True:
                    sentences.append(text)
                    partial.clear()
                else:
                    # 保留最新部分结果，供「录音很短、来不及断句」时兜底
                    partial[:] = [text]

            def on_complete(self) -> None:
                finished.set()

            def on_error(self, result) -> None:
                errors.append(str(result))
                finished.set()

            def on_close(self) -> None:
                finished.set()

        try:
            recognition = Recognition(
                model=(self.config.paraformer_model or "paraformer-realtime-v2").strip(),
                format="wav",
                sample_rate=ASR_SAMPLE_RATE,
                callback=_Callback(),
            )
            recognition.start()
        except Exception as error:
            logging.error("启动 Paraformer 失败: %s", error, exc_info=True)
            raise FailException("语音识别启动失败，请检查语音服务配置") from error

        try:
            for frame in frames:
                recognition.send_audio_frame(frame)
        finally:
            try:
                recognition.stop()
            except Exception:
                pass

        finished.wait(ASR_TOTAL_TIMEOUT)

        if errors and not sentences:
            logging.error("Paraformer 识别失败: %s", errors[:1])
            raise FailException("语音识别失败，请重试或改用浏览器识别")

        text = "".join(sentences).strip() or "".join(partial).strip()
        if not text:
            raise FailException("没有识别到语音内容，请靠近麦克风重新说一次")
        return text
