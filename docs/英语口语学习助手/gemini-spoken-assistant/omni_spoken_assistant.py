#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : omni_spoken_assistant.py
@Desc    : 基于阿里云百炼 Qwen3.8-Omni-Flash-Realtime 的英语口语学习助手

与 gemini_spoken_assistant.py 的差别：
1. 协议从 Gemini Live API 换成百炼 Omni-Realtime（原生 WebSocket + JSON 事件）；
2. 模型直接「音频进、音频出」，不再需要 ElevenLabs 做 TTS；
3. 支持用户随时打断（speech_started → response.cancel）。

运行前需在 .env 中配置：API_HOST / DASHSCOPE_API_KEY / MODEL / VOICE
"""
import asyncio
import base64
import json
import os
import queue
import sys
import threading
from pathlib import Path

import pyaudio
import websockets
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown

# Windows 控制台默认 GBK，中文与表情符号会抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# 音频参数（协议硬约束，不可随意改）
INPUT_RATE = 16000   # 上行采样率：必须 16000Hz
OUTPUT_RATE = 24000  # 下行采样率：必须 24000Hz
CHUNK_BYTES = 3200   # 100ms 的 s16le 单声道数据（16000 * 2 * 0.1）

# 预设人设（沿用原 Gemini 版本的纠错要求，并补充「能听发音」后的新能力）
INSTRUCTIONS = """你是一名专业的英语口语指导老师，请使用中文回复学生，帮助学生提升口语能力，回复尽可能简洁。

你的职责是：
1. 你能直接听到学生说话的声音，请结合语音本身判断重音、连读、语调、以及明显的音素错误；
2. 帮助学生纠正语法和发音；
3. 给出发音评分（0-100 分）并说明评分理由；
4. 理解并响应用户控制指令：
   - 当用户说 "Can I have a break" 时暂停
   - 当用户说 "OK let's continue" 时继续
5. 根据学生选择的主题和场景提供练习句子。

每当学生说完一个句子后，你需要：
1. 复述识别到的内容（中英文对照）
2. 给出发音评分（0-100 分），并给出评分理由
3. 详细说明发音和语法中的问题（中英文对照）
4. 提供一个同场景的下一个练习句子（中英文对照）

每次回复控制在 150 字以内，先讲问题再给练习句。"""


class OmniSpokenAssistant:
    """基于 Qwen3.8-Omni-Flash-Realtime 的英语口语学习助手"""

    console: Console          # 控制台实例
    pya: pyaudio.PyAudio      # Python 音频实例
    audio_queue: asyncio.Queue  # 麦克风音频队列
    paused: bool              # 暂停标识
    running_step: int         # 0 空闲 / 1 录音中 / 2 播放中
    _ws: object               # websocket 连接
    _out_stream: object       # 扬声器输出流
    _play_queue: queue.Queue  # 待播放音频块
    _play_suppressed: bool    # 当前回复是否丢弃播放（暂停态或已被打断）

    def __init__(self) -> None:
        """构造函数，完成配置读取与音频设备初始化"""
        self.api_host = os.getenv("API_HOST", "").strip()
        self.api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        self.model = os.getenv("MODEL", "qwen3.8-omni-flash-realtime").strip()
        self.voice = os.getenv("VOICE", "Aiden").strip()

        if not self.api_host or not self.api_key:
            raise RuntimeError("缺少 API_HOST 或 DASHSCOPE_API_KEY，请先填写 .env")

        self.console = Console()
        self.pya = pyaudio.PyAudio()
        self.audio_queue = asyncio.Queue()
        self.paused = False
        self.running_step = 0
        self._play_suppressed = False

    # ------------------------------------------------------------------ 会话
    def _url(self) -> str:
        """拼装业务空间专属的 WebSocket 地址"""
        return f"wss://{self.api_host}/api-ws/v1/realtime?model={self.model}"

    def _session_config(self) -> dict:
        """会话配置：语义 VAD + 音频格式 + 用户语音转写"""
        return {
            "modalities": ["text", "audio"],
            "instructions": INSTRUCTIONS,
            # 官方推荐 3.8 系列用 semantic_vad：能过滤背景音与他人附和声，减少误触发
            "turn_detection": {
                "type": "semantic_vad",
                "threshold": 0.1,
                "prefix_padding_ms": 500,
                "silence_duration_ms": 900,
            },
            "input_audio_transcription": {"model": "qwen3-asr-flash-realtime"},
            "audio": {
                "input": {
                    "format": {
                        "type": "pcm",
                        "sample_rate": INPUT_RATE,
                        "sample_format": "s16le",
                        "channels": 1,
                        "packing": "interleaved",
                        "channel_layout": "mono",
                    }
                },
                "output": {
                    "voice": self.voice,
                    "format": {"type": "pcm", "sample_rate": OUTPUT_RATE},
                },
            },
        }

    async def _asend(self, event: dict) -> None:
        """向服务端发送一个事件"""
        await self._ws.send(json.dumps(event))

    async def _ainit(self) -> None:
        """等待会话创建完成，下发配置并等确认"""
        while True:
            event = json.loads(await self._ws.recv())
            if event.get("type") == "error":
                raise RuntimeError(f"会话创建失败: {event}")
            if event.get("type") == "session.created":
                break

        await self._asend({"type": "session.update", "session": self._session_config()})
        while True:
            event = json.loads(await self._ws.recv())
            if event.get("type") == "error":
                raise RuntimeError(f"会话配置被拒: {event}")
            if event.get("type") == "session.updated":
                self.console.print("✅初始化完成", style="green")
                return

    # ------------------------------------------------------------------ 采集
    async def _alisten_audio(self) -> None:
        """持续采集麦克风音频并放入队列"""
        mic_info = self.pya.get_default_input_device_info()
        stream = self.pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=INPUT_RATE,
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=CHUNK_BYTES,
        )
        self.console.print("🎤请说英语", style="yellow")

        while True:
            # read 本身按 100ms 节奏阻塞，天然实现实时节流
            data = stream.read(CHUNK_BYTES, exception_on_overflow=False)

            # 音量检测，仅用于界面提示
            samples = [
                abs(int.from_bytes(data[i:i + 2], byteorder="little", signed=True))
                for i in range(0, len(data), 2)
            ]
            volume = sum(samples) / max(len(samples), 1)
            if volume > 200:
                if self.running_step == 0 and not self.paused:
                    self.console.print("🎤:", style="yellow", end="")
                    self.running_step = 1
                self.console.print("*", style="green", end="")

            await self.audio_queue.put(data)

    async def _asend_audio(self) -> None:
        """把队列中的音频以 input_audio_buffer.append 事件发给服务端"""
        while True:
            chunk = await self.audio_queue.get()
            try:
                await self._asend({
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode("ascii"),
                })
            except Exception as exc:  # 服务端可能因打断而临时拒收
                self.console.print(f"\n⚠️音频发送失败: {exc}", style="red")

    # ------------------------------------------------------------------ 接收
    def _start_player(self) -> None:
        """启动独立播放线程

        pyaudio 的 write 是阻塞的（约等于音频时长）。若放在事件循环里直接调用，
        会卡住麦克风上行与 speech_started 的响应，导致打断延迟、上行音频堆积。
        """
        self._play_queue = queue.Queue(maxsize=300)  # 约 30s 缓冲

        def worker() -> None:
            while True:
                chunk = self._play_queue.get()
                if chunk is None:
                    break
                try:
                    self._out_stream.write(chunk)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _play(self, chunk: bytes) -> None:
        """把音频块交给播放线程；暂停或被打断时直接丢弃"""
        if self._play_suppressed or self.paused:
            return
        try:
            self._play_queue.put_nowait(chunk)
        except queue.Full:
            pass

    def _drain_playback(self) -> None:
        """清空尚未播放的音频（打断时用）"""
        try:
            while True:
                self._play_queue.get_nowait()
        except queue.Empty:
            pass

    async def _areceive_events(self) -> None:
        """处理服务端事件：播放音频、打印文本、支持打断与暂停"""
        response_text = []

        while True:
            event = json.loads(await self._ws.recv())
            etype = event.get("type")

            # 1.错误
            if etype == "error":
                msg = event.get("error", {}).get("message", "")
                self.console.print(f"\n❌服务端错误: {msg}", style="red")
                continue

            # 2.用户开口 → 打断当前回复，清空本地播放缓存
            if etype == "input_audio_buffer.speech_started":
                if self.running_step == 2 or response_text:
                    self._play_suppressed = True
                    self._drain_playback()
                    await self._asend({"type": "response.cancel"})
                    self.console.print("\n✋已打断", style="yellow")

            # 3.用户语音识别完成 → 打印原文，并处理语音控制指令
            elif etype == "conversation.item.input_audio_transcription.completed":
                transcript = (event.get("transcript") or "").strip()
                if transcript:
                    self.console.print(f"\n🧑你: {transcript}", style="cyan")
                    lowered = transcript.lower()
                    if "can i have a break" in lowered and not self.paused:
                        self.paused = True
                        self._play_suppressed = True
                        self._drain_playback()
                        await self._asend({"type": "response.cancel"})
                        self.console.print(
                            "⏸️会话已暂停。说 'OK let's continue' 继续", style="yellow"
                        )
                    elif "ok let's continue" in lowered and self.paused:
                        self.paused = False
                        self._play_suppressed = False
                        self.console.print("▶️会话继续", style="green")

            # 4.助手音频增量 → 直接播放
            elif etype == "response.audio.delta":
                if self.running_step != 2 and not self.paused:
                    self.running_step = 2
                self._play(base64.b64decode(event["delta"]))

            # 5.助手文本增量（部分版本只给 done，两种都接）
            elif etype in ("response.audio_transcript.delta", "response.text.delta"):
                response_text.append(event.get("delta", ""))

            elif etype in ("response.audio_transcript.done", "response.text.done"):
                text = event.get("transcript") or event.get("text") or ""
                if text and not response_text:
                    response_text.append(text)

            # 6.一轮回复结束
            elif etype == "response.done":
                text = "".join(response_text).strip()
                status = event.get("response", {}).get("status")
                if text and not self.paused:
                    self.console.print(
                        "\n👴🏼=============================================", style="yellow"
                    )
                    self.console.print(Markdown(text))
                if status not in (None, "completed"):
                    self.console.print(f"⚠️本轮状态: {status}", style="yellow")
                response_text = []
                self._play_suppressed = False
                self.running_step = 0 if not self.paused else 2

    # ------------------------------------------------------------------ 启动
    async def arun(self) -> None:
        """建立连接并启动三个并发任务"""
        self.console.print("英语口语学习助手 · Qwen3.8-Omni-Flash-Realtime", style="green")
        self.console.print(f"模型: {self.model}   音色: {self.voice}", style="blue")
        self.console.print("============================================", style="yellow")

        self._out_stream = self.pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=OUTPUT_RATE,
            output=True,
            frames_per_buffer=CHUNK_BYTES,
        )
        self._start_player()

        async with websockets.connect(
            self._url(),
            additional_headers={"Authorization": f"Bearer {self.api_key}"},
            max_size=None,
            open_timeout=20,
        ) as ws:
            self._ws = ws
            await self._ainit()
            await asyncio.gather(
                self._alisten_audio(),
                self._asend_audio(),
                self._areceive_events(),
            )


if __name__ == "__main__":
    assistant = OmniSpokenAssistant()
    try:
        asyncio.run(assistant.arun())
    except KeyboardInterrupt:
        print("\n会话结束")
