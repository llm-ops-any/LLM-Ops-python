import { type BaseResponse } from '@/models/base'

// 大模型服务设置信息（不含密钥明文）
export type ModelProviderSetting = {
  base_url: string
  has_api_key: boolean
  masked_api_key: string
  source: string
  source_label: string
}

// 获取大模型服务设置响应结构
export type GetModelProviderResponse = BaseResponse<ModelProviderSetting>

// 测试大模型服务连通性响应结构
export type TestModelProviderConnectionResponse = BaseResponse<{
  ok: boolean
  status: number
  message: string
  model_count: number
}>
