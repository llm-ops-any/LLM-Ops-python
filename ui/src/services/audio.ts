import { get, post, ssePost, upload } from '@/utils/request'
import type {
  AudioToTextResponse,
  GetSpeechProviderResponse,
  TestSpeechProviderResponse,
  UpdateSpeechProviderRequest,
} from '@/models/audio'

// 获取语音服务配置
export const getSpeechProvider = () => {
  return get<GetSpeechProviderResponse>(`/speech-provider`)
}

// 保存语音服务配置，dashscope_api_key 为空表示不修改已保存的密钥
export const updateSpeechProvider = (req: UpdateSpeechProviderRequest) => {
  return post<GetSpeechProviderResponse>(`/speech-provider`, { body: req })
}

// 测试当前语音引擎能否真的出声
export const testSpeechProvider = () => {
  return post<TestSpeechProviderResponse>(`/speech-provider/test`, { body: {} })
}

// 语音转文本：上传 WAV（服务端只支持 16k 单声道 WAV）
export const audioToText = (blob: Blob) => {
  const formData = new FormData()
  formData.append('file', blob, 'recording.wav')
  return upload<AudioToTextResponse>(`/audio/audio-to-text`, { data: formData })
}

// 消息转语音：SSE 流式返回 base64 PCM
export const messageToAudio = (
  message_id: string,
  onData: (event_response: Record<string, any>) => void,
) => {
  return ssePost(`/audio/message-to-audio`, { body: { message_id } }, onData)
}
