import base64
import os
import uuid
from pathlib import Path

import dotenv
import gradio as gr
import requests

dotenv.load_dotenv()

def fetch_data(query: str):
    """调用开放API获取对应Agent生成的文案内容"""
    # 1.从环境变量中获取数据
    url = os.getenv("LLMOPS_API_BASE")
    api_key = os.getenv("LLMOPS_API_KEY")
    app_id = os.getenv("LLMOPS_APP_ID")

    # 2.组装请求头
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # 3.组装请求数据
    request_body = {
        "app_id": app_id,
        "end_user_id": "",
        "conversation_id": "",
        "stream": False,
        "query": query,
        "image_urls": [],
    }

    try:
        # 4.使用requests包发起post请求
        response = requests.post(url, json=request_body, headers=headers)
        if response.status_code == 200:
            data = response.json()
            return data["data"]["answer"]
        else:
            return f"请求失败：{response.status_code}"
    except Exception as e:
        return f"请求异常：{str(e)}"


def text_to_speech(text: str):
    """调用阿里百炼 Qwen-Audio-TTS 把文案合成为音频，返回本地文件路径"""
    text = (text or "").strip()
    if not text:
        raise gr.Error("文案内容为空，请先获取或填写文案")

    # 1.从环境变量中获取百炼配置（默认 qwen-audio-3.1-tts-flash，走 TTS 专用接口）
    api_key = os.getenv("DASHSCOPE_API_KEY")
    tts_url = os.getenv(
        "DASHSCOPE_TTS_URL",
        "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/SpeechSynthesizer",
    )
    model = os.getenv("TTS_MODEL", "qwen-audio-3.1-tts-flash")
    voice = os.getenv("TTS_VOICE", "longanhuan_v3.1")
    if not api_key:
        raise gr.Error("未配置 DASHSCOPE_API_KEY，请检查 .env")

    # 2.组装请求（百炼原生接口，返回的是音频下载地址而不是字节流）
    #    注意：qwen3-tts 系列认 language_type，qwen-audio-tts / cosyvoice 认 language_hints + format
    if model.startswith("qwen3-tts"):
        audio_input = {"text": text, "voice": voice, "language_type": "Chinese"}
    else:
        audio_input = {
            "text": text,
            "voice": voice,
            "format": "mp3",
            "sample_rate": 24000,
            "language_hints": ["zh"],
        }
    payload = {"model": model, "input": audio_input}
    try:
        response = requests.post(
            tts_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=120,
        )
        if response.status_code != 200:
            raise gr.Error(f"百炼返回 {response.status_code}：{response.text[:200]}")

        # 3.取出音频（正常是 download url，个别模型直接给 base64）
        audio_info = (response.json().get("output") or {}).get("audio") or {}
        audio_bytes = b""
        if audio_info.get("url"):
            audio_bytes = requests.get(audio_info["url"], timeout=120).content
        elif audio_info.get("data"):
            audio_bytes = base64.b64decode(audio_info["data"])
        if not audio_bytes:
            raise gr.Error(f"百炼未返回音频数据：{response.text[:200]}")

        # 4.落盘后交给 Audio 组件播放
        audio_dir = Path(__file__).parent / "storage" / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_file = audio_dir / f"{uuid.uuid4()}.mp3"
        audio_file.write_bytes(audio_bytes)
        return str(audio_file)
    except gr.Error:
        raise
    except Exception as e:
        # Audio 输出只接受文件路径，返回字符串会被当成路径去读取而崩掉整个请求，这里改为弹窗报错
        raise gr.Error(f"语音生成失败：{e}")

# WebUI界面的部分
with gr.Blocks() as webui:
    with gr.Row():
        with gr.Column(scale=1):
            # 数字人主题输入框&点击按钮
            input_box = gr.Textbox(label="文案主题", placeholder="请输入数字人口播文案主题")
            fetch_button = gr.Button("获取文案")
            output_box = gr.Textbox(
                label="文案内容",
                placeholder="请输入数字人口播文案内容或通过AI生成",
                lines=5,
                interactive=True
            )

            # 将文案装换成音频
            tts_button = gr.Button("转换为语音")
            audio_output = gr.Audio(label="语音音频", type="filepath")

        # 绑定事件
        fetch_button.click(fetch_data, inputs=input_box, outputs=output_box)
        tts_button.click(text_to_speech, inputs=output_box, outputs=audio_output)
        audio_output.change(None, inputs=audio_output)
        with gr.Column(scale=2):
            gr.Markdown("视频")

webui.launch()
