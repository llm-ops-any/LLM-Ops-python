#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2025/01/24 9:34
@Author  : thezehui@gmail.com
@File    : gemini_spoken_assistant.py
"""
import asyncio
import base64

import pyaudio
from elevenlabs import ElevenLabs, play
from google.genai import Client
from google.genai.live import AsyncSession
from pyaudio import PyAudio
from rich.console import Console
from rich.markdown import Markdown


class GeminiSpokenAssistant:
    """基于Gemini的英语口语学习助手"""
    client: Client  # genai客户端
    session: AsyncSession  # websocket会话
    console: Console  # 控制台实例
    pya: PyAudio  # Python音频实例
    voice_client: ElevenLabs  # 语音客户端实例
    audio_queue: asyncio.Queue  # 音频队列
    chunk_size: int  # 缓存冲大小
    paused: bool  # 暂停标识
    running_step: int  # 当前运行步骤，0为空闲，1为录音中，2为播放中

    def __init__(
            self,
            gemini_api_key: str = None,
            eleven_labs_api_key: str = None,
    ) -> None:
        """构造函数，完成口语学习助手的初始化"""
        self.client = Client(
            api_key=gemini_api_key,
            http_options={"api_version": "v1alpha"}
        )
        self.console = Console()
        self.pya = pyaudio.PyAudio()
        self.running_step = 0
        self.voice_client = ElevenLabs(api_key=eleven_labs_api_key)
        self.audio_queue = asyncio.Queue()
        self.chunk_size = 512
        self.paused = False
        self.running_step = 0

    async def _ainit(self) -> None:
        """口语助手会话初始化，完成预设prompt的填充"""
        # 1.传递预设的prompt消息
        init_prompt = """你是一名专业的英语口语指导老师, 请使用中文回复学生, 并帮助用户提升口语能力, 回复尽可能简洁.

你的职责是：
1. 帮助用户纠正语法和发音
2. 给出发音评分和详细反馈
3. 理解并响应用户控制指令:
    - 当用户说"Can I have a break"时暂停
    - 当用户说"OK let's continue"时继续
4. 根据用户发送的句子选择的主题和场景提供练习句子

每当用户说完一个句子后, 你需要:
1. 识别用户说的内容(中英文对照)
2. 给出发音评分(0-100分), 并给出评分理由
3. 详细说明发音和语法中的问题(中英文对照)
5. 提供下一个场景相关的练习句子(中英文对照)

如果您能理解需求，请回复"OK"."""
        await self.session.send(
            input=init_prompt,
            end_of_turn=True,
        )

        # 2.等待AI回复OK代表助手初始化完成
        current_response = []
        async for response in self.session.receive():
            try:
                # 3.提取输出内容并循环遍历将数据添加到current_response
                parts = response.server_content.model_turn.parts
                current_response.extend([part.text for part in parts if part.text])
            except Exception:
                pass

            try:
                # 4.获取websocket中流式输出的结束标记
                turn_complete = response.server_content.turn_complete
                if turn_complete:
                    # 5.拼接输出内容并检查是否包含OK
                    if "".join(current_response).strip().startswith("OK"):
                        self.console.print("✅初始化完成", style="green")
                        return
            except Exception:
                pass

    async def _alisten_audio(self):
        """异步监听麦克风的语音输入信息"""
        # 1.获取默认麦克风的相关信息
        mic_info = self.pya.get_default_input_device_info()

        # 2.创建音频输入流
        stream = self.pya.open(
            format=pyaudio.paInt16,  # 16位音频格式
            channels=1,  # 单声道
            rate=16000,  # 输入采样率
            input=True,
            input_device_index=mic_info["index"],
            frames_per_buffer=self.chunk_size,
        )
        self.console.print("🎤请说英语", style="yellow")

        # 3.执行死循环监听语音输入
        while True:
            # 4.如果暂停则休眠0.1s并跳过当前处理
            if self.paused:
                await asyncio.sleep(0.1)
                continue

            # 5.异步读取音频输入，如果正在录音or处理中则跳过
            data = await asyncio.to_thread(stream.read, self.chunk_size)
            if self.running_step > 1:
                continue

            # 6.实时音量检测，根据音量触发交互显示
            audio_data = []
            for i in range(0, len(data), 2):
                sample = int.from_bytes(data[i:i + 2], byteorder="little", signed=True)
                audio_data.append(abs(sample))
            volume = sum(audio_data) / len(audio_data)
            if volume > 200:
                # 7.检测是否处于空闲状态，是则更新状态并输出*模拟录音进度条
                if self.running_step == 0:
                    self.console.print("🎤:", style="yellow", end="")
                    self.running_step += 1
                self.console.print("*", style="green", end="")

            # 8.将音频数据添加到队列中
            await self.audio_queue.put(data)

    async def _asend_audio(self):
        """发送语音输入处理器"""
        # 1.创建死循环发送音频数据给LLM
        while True:
            # 2.如果当前处于暂停状态则休眠0.1s后继续
            if self.paused:
                await asyncio.sleep(0.1)
                continue

            # 3.从异步队列中获取数据
            chunk = await self.audio_queue.get()

            # 4.组装gemini消息格式并发送
            #   参考链接: https://ai.google.dev/gemini-api/docs/multimodal-live#bidigeneratecontentrealtimeinput
            await self.session.send(
                input={
                    "media_chunks": {
                        "data": base64.b64encode(chunk).decode(),
                        "mime_type": "audio/pcm",
                    }
                }
            )

            # 5.休眠0.1s
            await asyncio.sleep(0.1)

    async def _areceive_audio(self) -> None:
        """接口Gemini返回的文本并生成音频进行播放"""
        while True:
            # 1.定义变量存储websocket推送的内容
            current_response = []

            # 2.循环遍历所有内容信息
            async for response in self.session.receive():
                # 3.判断当前运行步骤
                if self.running_step == 1:
                    self.console.print("\n👨🏻‍💻处理中:", end="")
                    self.running_step += 1

                try:
                    # 4.提取parts内容
                    parts = response.server_content.model_turn.parts

                    # 5.循环遍历parts并提取内容
                    for part in parts:
                        if part.text:
                            # 6.如果输出存在文本则提取打印-代表正在处理
                            current_response.append(part.text)
                            self.console.print("-", style="blue", end="")
                except Exception:
                    pass

                try:
                    # 7.提取结束标识，并判断是否结束
                    turn_complete = response.server_content.turn_complete
                    if turn_complete and current_response:
                        text = "".join(current_response).strip()

                        # 8.检查是否是控制命令
                        if "can i have a break" in text.lower():
                            self.paused = True
                            self.console.print("\n⏸️会话已暂停。说 'OK let's continue' 继续", style="yellow")
                        elif "ok let's continue" in text.lower() and self.paused:
                            self.paused = False
                            self.console.print("\n▶️会话继续", style="green")

                        # 9.显示gemini返回的文本信息
                        self.console.print("\n👴🏼=============================================", style="yellow")
                        self.console.print(Markdown(text))

                        # 10.播放语音
                        if self.voice_client and not self.paused:
                            try:
                                def play_audio():
                                    play_text = "".join(current_response).strip()
                                    if len(text) > 0:
                                        voice_stream = self.voice_client.text_to_speech.convert_as_stream(
                                            voice_id="nPczCjzI2devNBz1zQrb",
                                            text=play_text,
                                            model_id="eleven_flash_v2_5",
                                        )
                                        play(voice_stream)

                                self.console.print("📞声音播放中...", style="yellow")
                                await asyncio.to_thread(play_audio)
                                self.console.print("📞播放完毕", style="green")
                            except Exception as e:
                                self.console.print(f"❌语音播放错误: {e}")

                        # 11.清空response
                        current_response = []
                        self.running_step = 0 if not self.paused else 2
                except Exception:
                    pass
            await asyncio.sleep(0.1)

    async def ainvoke(self) -> None:
        # 1.创建一个websocket连接会话
        async with self.client.aio.live.connect(
                model="gemini-2.0-flash-exp",  # 配置模型为gemini-2.0-flash-exp
                config={"response_modalities": ["TEXT"]},  # 配置响应格式为TEXT，语音生成部分使用其他模块完成
        ) as session:
            # 2.将当前会话赋值给session并存储
            self.session = session
            self.console.print("慕课英语口语学习助手", style="green", highlight=True)
            self.console.print("============================================", style="yellow")

            # 3.调用初始化处理器启动服务并预设内容
            await self._ainit()

            # 4.创建异步任务列表
            tasks = [
                asyncio.create_task(self._alisten_audio()),
                asyncio.create_task(self._asend_audio()),
                asyncio.create_task(self._areceive_audio()),
            ]

            await asyncio.gather(*tasks)


if __name__ == "__main__":
    spoken_assistant = GeminiSpokenAssistant(
        gemini_api_key="",
        eleven_labs_api_key="",
    )
    asyncio.run(spoken_assistant.ainvoke())
