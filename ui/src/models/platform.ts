import type { BaseResponse } from '@/models/base'

// 获取微信配置响应结构（CR-16102807）
export type GetWechatConfigResponse = BaseResponse<{
  app_id: string
  /** 回调地址，形如 {SERVICE_API_PREFIX}/wechat/{app_id} */
  url: string
  /** 服务器 IP，来自 SERVICE_IP */
  ip: string
  wechat_app_id: string
  wechat_app_secret: string
  wechat_token: string
  /** configured | unconfigured（后端推导，前端不写） */
  status: string
  updated_at: number
  created_at: number
}>

// 更新微信配置请求结构
export type UpdateWechatConfigRequest = {
  wechat_app_id?: string
  wechat_app_secret?: string
  wechat_token?: string
}
