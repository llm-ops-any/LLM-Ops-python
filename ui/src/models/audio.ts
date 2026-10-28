import type { BaseResponse } from '@/models/base'

// 语音引擎：browser=浏览器原生 / omni=Qwen-Omni-Realtime / dashscope=CosyVoice+Paraformer
export type SpeechEngine = 'browser' | 'omni' | 'dashscope'

// 引擎候选（后端下发，避免前后端各写一份文案）
export type SpeechEngineOption = {
  value: SpeechEngine
  label: string
}

// 语音服务配置结构（不含密钥明文）
export type SpeechProviderSetting = {
  engine: SpeechEngine
  has_api_key: boolean
  masked_api_key: string
  omni_model: string
  omni_voice: string
  omni_host: string
  cosyvoice_model: string
  cosyvoice_voice: string
  paraformer_model: string
  source: string
  source_label: string
  engines: SpeechEngineOption[]
  omni_voice_options: string[]
  cosyvoice_voice_options: string[]
}

// 获取语音服务配置响应
export type GetSpeechProviderResponse = BaseResponse<SpeechProviderSetting>

// 更新语音服务配置请求（所有字段可选，只传要改的）
export type UpdateSpeechProviderRequest = {
  engine?: SpeechEngine
  dashscope_api_key?: string
  omni_model?: string
  omni_voice?: string
  omni_host?: string
  cosyvoice_model?: string
  cosyvoice_voice?: string
  paraformer_model?: string
}

// 连通性测试结果
export type TestSpeechProviderResponse = BaseResponse<{
  ok: boolean
  engine: SpeechEngine
  message: string
  bytes: number
}>

// 语音转文本响应
export type AudioToTextResponse = BaseResponse<{ text: string }>

// 消息转语音的 SSE 事件载荷
export type TTSMessagePayload = {
  conversation_id: string
  message_id: string
  audio: string
  sample_rate: number
  engine?: SpeechEngine
}
