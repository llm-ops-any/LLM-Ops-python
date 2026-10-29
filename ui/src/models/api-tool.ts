import { type BasePaginatorResponse, type BaseResponse } from '@/models/base'

// API插件请求头，响应中的value永远是掩码(****)，has_value表示该请求头是否已保存密钥
export type ApiToolHeader = {
  key: string
  value: string
  has_value?: boolean
}

// 获取自定义API插件响应接口
export type GetApiToolProvidersWithPageResponse = BasePaginatorResponse<{
  id: string
  name: string
  icon: string
  description: string
  headers: ApiToolHeader[]
  tools: Array<any>
  created_at: number
}>

// 新增自定义API插件提供者请求结构
export type CreateApiToolProviderRequest = {
  name: string
  icon: string
  openapi_schema: string
  headers: Array<any>
}

// 更新自定义API工具提供者请求与响应结构
export type UpdateApiToolProviderRequest = {
  name: string
  icon: string
  openapi_schema: string
  headers: Array<any>
}

// 获取自定义API工具提供者响应结构体
export type GetApiToolProviderResponse = BaseResponse<{
  id: string
  name: string
  icon: string
  openapi_schema: string
  headers: ApiToolHeader[]
  created_at: number
}>

// 获取自定义API工具详情
export type GetApiToolResponse = BaseResponse<{
  id: string
  name: string
  description: string
  provider: {
    id: string
    name: string
    icon: string
    headers: ApiToolHeader[]
    description: string
  }
  inputs: {
    type: string
    name: string
    required: boolean
    description: string
  }[]
}>
