import os
import dotenv
import gradio as gr
import requests
from openai import OpenAI

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
    """将传递的文本转换成音频数据"""
    try:
        client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_API_KEY")
            )
        response = client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            response_format="mp3",
            input=text,
        )
        audio_file = Path(__file__).parent / f"storage/audio/{str(uuid.uuid4())}.mp3"
        response.stream_to_file(audio_file)
        return audio_file
    except Exception as e:
        return f"语音生成失败：{str(e)}"

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
