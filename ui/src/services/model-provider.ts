import { get, post } from '@/utils/request'
import {
  type GetModelProviderResponse,
  type TestModelProviderConnectionResponse,
} from '@/models/model-provider'

// 获取大模型服务设置
export const getModelProvider = () => {
  return get<GetModelProviderResponse>(`/model-provider`)
}

// 保存大模型服务设置，apiKey为空表示不修改已保存的密钥
export const updateModelProvider = (base_url: string, api_key: string) => {
  return post<GetModelProviderResponse>(`/model-provider`, {
    body: { base_url, api_key },
  })
}

// 测试大模型服务连通性
export const testModelProviderConnection = (base_url: string, api_key: string) => {
  return post<TestModelProviderConnectionResponse>(`/model-provider/test-connection`, {
    body: { base_url, api_key },
  })
}
