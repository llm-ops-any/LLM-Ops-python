import { type BasePaginatorRequest, type BasePaginatorResponse } from '@/models/base'
import { type ChatAttachment } from '@/models/upload-file'

// 获取指定会话消息列表请求结构
export type GetConversationMessagesWithPageRequest = BasePaginatorRequest & {
  created_at: number
}

// 获取指定会话消息列表响应结构
export type GetConversationMessagesWithPageResponse = BasePaginatorResponse<{
  id: string
  conversation_id: string
  query: string
  answer: string
  total_token_count: number
  latency: number
  agent_thoughts: {
    id: string
    position: number
    event: string
    thought: string
    observation: string
    tool: string
    tool_input: Record<string, any>
    latency: number
    created_at: number
  }[]
  // 随消息上传的附件(服务端已持久化，历史消息与新消息都会回传，用于展示附件标签)
  attachments?: ChatAttachment[]
  created_at: number
}>
