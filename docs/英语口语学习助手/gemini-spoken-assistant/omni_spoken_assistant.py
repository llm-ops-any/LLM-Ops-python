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
import time
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
ECHO_TAIL_SEC = 0.4  # 播完后再多压一会儿上行，吃掉拖尾回声

# 预设人设（沿用原 Gemini 版本的纠错要求，并补充「能听发音」后的新能力）
INSTRUCTIONS = """# 角色
你是英语口语教练。学生说的每一句英语都是「朗读练习材料」，不是在向你提问或打招呼。

# 铁律
1. 严禁回答、回应、翻译或评论学生句子的【内容含义】。听到 "Hello" 不许回 "Hi/你好"，听到 "How are you" 不许回 "我很好"。
2. 严禁寒暄、鼓励、夸奖（不许出现 "很好""不错""继续加油"）。
3. 每次回复必须严格使用下面的四行模板，一行都不能少、不能多，不加任何开场白和结尾。

# 输出模板
听到：<学生说的英文原文>
评分：<0-100> 分，理由：<一句话，指出最明显的一处发音问题>
问题：<具体音素/重音/连读或语法错误，必须中英对照，例："th 发成了 /s/（th 应咬舌，读 /θ/ 不是 /s/）">
练习：<同场景下一个练习句>（<中文翻译>）

# 评分依据
你能直接听到学生的声音，请结合重音、连读、语调、音素准确度打分，不要只看文字。

# 例外：控制指令
只有学生明确说出 "Can I have a break" 或 "OK let's continue" 时，才脱离模板，只回复一句确认语。"""

# 需要调人设时直接改同目录下的 prompt.txt，不必动代码
_PROMPT_FILE = Path(__file__).resolve().parent / "prompt.txt"
if _PROMPT_FILE.exists():
    INSTRUCTIONS = _PROMPT_FILE.read_text(encoding="utf-8").strip()


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
        # 不指定时服务端按中文识别，说英语会被转成中文，练习口语必须锁 en
        self.asr_language = os.getenv("ASR_LANGUAGE", "en").strip()
        # server_vad 按声学特征断句（与语种无关）；semantic_vad 按语义有效性断句，
        # 对中文优化，说英语会被判成无效语音而完全不触发，练习英语必须用 server_vad
        self.vad_type = os.getenv("VAD_TYPE", "server_vad").strip()
        # 判定「用户说完了」所需的静音时长（毫秒）：说完后要静默多久才开始回复
        try:
            self.silence_ms = int(os.getenv("SILENCE_MS", "3000").strip())
        except ValueError:
            self.silence_ms = 3000
        # 设备选择：填 index（如 3）或名称片段（如 "耳机"），留空用系统默认
        self.mic_device = os.getenv("MIC_DEVICE", "").strip()
        self.output_device = os.getenv("OUTPUT_DEVICE", "").strip()
        # 用外放时助手的声音会被麦克风收回去形成回声环路，播报期间必须掐断上行。
        # 用耳机（或做了系统级 AEC）时可设 ECHO_GATE=0 恢复随时打断
        self.echo_gate = os.getenv("ECHO_GATE", "1").strip() not in ("0", "false", "False")

        if not self.api_host or not self.api_key:
            raise RuntimeError("缺少 API_HOST 或 DASHSCOPE_API_KEY，请先填写 .env")

        self.console = Console()
        self.pya = pyaudio.PyAudio()
        self.audio_queue = asyncio.Queue()
        self.paused = False
        self.running_step = 0
        self._play_suppressed = False
        self._speaking = False    # 是否正在外放助手语音
        self._gate_until = 0.0    # 回声门控解除时刻

    def _resolve_device(self, spec: str, kind: str) -> object:
        """解析 .env 里的 MIC_DEVICE / OUTPUT_DEVICE

        kind: "input" 或 "output"。纯数字按索引取，否则按名称片段匹配；
        留空返回 None，交给 PortAudio 用系统默认设备。
        """
        if not spec:
            return None
        key = "maxInputChannels" if kind == "input" else "maxOutputChannels"
        if spec.lstrip("-").isdigit():
            return int(spec)
        for i in range(self.pya.get_device_count()):
            try:
                info = self.pya.get_device_info_by_index(i)
            except OSError:
                continue
            if info.get(key, 0) > 0 and spec.lower() in str(info["name"]).lower():
                return int(info["index"])
        raise RuntimeError(f"找不到{kind}设备: {spec}（用 python _list_devices.py 查看）")

    @staticmethod
    def _iter_devices(pya: pyaudio.PyAudio, kind: str):
        """按索引遍历设备（PyAudio 没有设备生成器）"""
        key = "maxInputChannels" if kind == "input" else "maxOutputChannels"
        for i in range(pya.get_device_count()):
            try:
                info = pya.get_device_info_by_index(i)
            except OSError:
                continue
            if info.get(key, 0) > 0:
                yield int(info["index"]), str(info["name"])

    def _can_open_output(self, idx: int) -> bool:
        """用真实参数（24kHz/16bit/单声道）试着打开，打不开的一律排除"""
        try:
            stream = self.pya.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=OUTPUT_RATE,
                output=True,
                output_device_index=idx,
            )
        except Exception:
            return False
        stream.close()
        return True

    def _auto_output_device(self) -> tuple:
        """自动选扬声器：先按真实参数试开过滤，再按名称打分排序

        打分规则（设备名中文部分是乱码，只能靠 ASCII 关键词）：
          +50 命中 speaker/headphone/headset/edifier/realtek/usb/analog（真音箱耳机）
          -40 命中 nvidia/hdmi/hands-free/virtual（显卡 HDMI 口、蓝牙免提、虚拟设备）
          +10 命中 mapper（声音映射器，会跟随 Windows 默认设备，比较稳）
          +20 是系统默认输出设备
        """
        default_idx = int(self.pya.get_default_output_device_info()["index"])
        positive = ("speaker", "headphone", "headset", "edifier", "realtek", "usb", "analog")
        negative = ("nvidia", "hdmi", "hands-free", "virtual")
        neutral = ("mapper",)

        scored = []
        for idx, name in self._iter_devices(self.pya, "output"):
            if not self._can_open_output(idx):
                continue
            low = name.lower()
            score = 0
            if any(k in low for k in positive):
                score += 50
            if any(k in low for k in negative):
                score -= 40
            if any(k in low for k in neutral):
                score += 10
            if idx == default_idx:
                score += 20
            scored.append((score, idx, name))

        if not scored:  # 全都打不开，退回系统默认
            return default_idx, self.pya.get_device_info_by_index(default_idx)["name"], False

        scored.sort(key=lambda item: (-item[0], item[1]))
        _, best_idx, best_name = scored[0]
        return best_idx, best_name, True

    def _resolve_output(self) -> tuple:
        """决定用哪个输出设备：.env 显式指定优先，auto/留空则自动探测"""
        spec = self.output_device.lower()
        if spec and spec != "auto":
            idx = self._resolve_device(self.output_device, "output")
            if idx is None:
                idx = int(self.pya.get_default_output_device_info()["index"])
            return int(idx), self.pya.get_device_info_by_index(idx)["name"], False
        return self._auto_output_device()

    # ------------------------------------------------------------------ 会话
    def _url(self) -> str:
        """拼装业务空间专属的 WebSocket 地址"""
        return f"wss://{self.api_host}/api-ws/v1/realtime?model={self.model}"

    def _session_config(self) -> dict:
        """会话配置：语义 VAD + 音频格式 + 用户语音转写"""
        return {
            "modalities": ["text", "audio"],
            "instructions": INSTRUCTIONS,
            "turn_detection": {
                "type": self.vad_type,
                "threshold": 0.3,
                "prefix_padding_ms": 300,
                "silence_duration_ms": self.silence_ms,
            },
            "input_audio_transcription": {
                "model": "qwen3-asr-flash-realtime",
                "language": self.asr_language,
            },
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
        mic_idx = self._resolve_device(self.mic_device, "input")
        if mic_idx is None:
            mic_idx = int(self.pya.get_default_input_device_info()["index"])
        stream = self.pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=INPUT_RATE,
            input=True,
            input_device_index=mic_idx,
            frames_per_buffer=CHUNK_BYTES,
        )
        self.console.print("🎤请说英语", style="yellow")

        loop = asyncio.get_event_loop()
        while True:
            # 必须丢到线程里：read 是阻塞 C 调用，直接在协程里调会卡死事件循环，
            # 导致发送/接收任务永远得不到调度（音频根本发不出去）
            data = await loop.run_in_executor(
                None, lambda: stream.read(CHUNK_BYTES, exception_on_overflow=False)
            )

            # 外放期间麦克风收到的全是回声，界面上不要再显示音量条误导用户
            gated = self.echo_gate and (
                self._speaking or time.monotonic() < self._gate_until
            )

            # 音量检测，仅用于界面提示
            samples = [
                abs(int.from_bytes(data[i:i + 2], byteorder="little", signed=True))
                for i in range(0, len(data), 2)
            ]
            volume = sum(samples) / max(len(samples), 1)
            if volume > 200 and not gated:
                if self.running_step == 0 and not self.paused:
                    self.console.print("🎤:", style="yellow", end="")
                    self.running_step = 1
                self.console.print("*", style="green", end="")

            await self.audio_queue.put(data)

    async def _asend_audio(self) -> None:
        """把队列中的音频以 input_audio_buffer.append 事件发给服务端"""
        while True:
            chunk = await self.audio_queue.get()

            # 回声门控：外放期间不上行，否则助手会听到自己的声音并无限自我回复
            if self.echo_gate and (self._speaking or time.monotonic() < self._gate_until):
                continue

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
                finally:
                    # 队列见底才算真的播完，放开门控再多压一小段吃掉拖尾回声
                    if self._play_queue.empty():
                        self._speaking = False
                        self._gate_until = time.monotonic() + ECHO_TAIL_SEC

        threading.Thread(target=worker, daemon=True).start()

    def _play(self, chunk: bytes) -> None:
        """把音频块交给播放线程；暂停或被打断时直接丢弃"""
        if self._play_suppressed or self.paused:
            return
        try:
            self._play_queue.put_nowait(chunk)
            self._speaking = True
        except queue.Full:
            pass

    def _drain_playback(self) -> None:
        """清空尚未播放的音频（打断时用）"""
        try:
            while True:
                self._play_queue.get_nowait()
        except queue.Empty:
            pass
        self._speaking = False
        self._gate_until = time.monotonic() + ECHO_TAIL_SEC

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

            # 5.助手开始回复 → 先打分隔线，后续增量流式输出，避免干等
            elif etype == "response.created":
                if not self.paused:
                    self.console.print(
                        "\n👴🏼=============================================", style="yellow"
                    )

            # 6.助手文本增量（部分版本只给 done，两种都接）
            elif etype in ("response.audio_transcript.delta", "response.text.delta"):
                delta = event.get("delta", "")
                response_text.append(delta)
                if delta and not self.paused:
                    self.console.print(delta, style="yellow", end="")

            elif etype in ("response.audio_transcript.done", "response.text.done"):
                text = event.get("transcript") or event.get("text") or ""
                if text and not response_text:
                    response_text.append(text)
                    if not self.paused:
                        self.console.print(Markdown(text))

            # 7.一轮回复结束
            elif etype == "response.done":
                status = event.get("response", {}).get("status")
                if response_text and not self.paused:
                    self.console.print("")
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
        self.console.print(
            f"说完等待: {self.silence_ms}ms   回声门控: {'开' if self.echo_gate else '关'}",
            style="blue",
        )
        self.console.print("============================================", style="yellow")

        out_idx, out_name, auto = self._resolve_output()
        tag = "自动选择" if auto else "指定"
        self.console.print(
            f"🔊扬声器[{tag}]: index={out_idx}  {out_name}", style="blue"
        )
        self._out_stream = self.pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=OUTPUT_RATE,
            output=True,
            output_device_index=out_idx,
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
