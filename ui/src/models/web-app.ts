import type { BaseResponse } from '@/models/base'
import type { ChatAttachment } from '@/models/upload-file'

// 获取WebApp基础信息响应结构
export type GetWebAppResponse = BaseResponse<{
  id: string
  icon: string
  name: string
  description: string
  app_config: {
    opening_statement: string
    opening_questions: string[]
    suggested_after_answer: {
      enable: boolean
    }
  }
}>

// 获取WebApp会话消息列表响应结构
export type GetWebAppConversationsResponse = BaseResponse<
  {
    id: string
    name: string
    summary: string
    created_at: number
  }[]
>

// 与WebApp对话请求结构
export type WebAppChatRequest = {
  conversation_id?: string
  query: string
  // 随消息上传的附件(由服务端解析出的文本)
  files?: ChatAttachment[]
}
