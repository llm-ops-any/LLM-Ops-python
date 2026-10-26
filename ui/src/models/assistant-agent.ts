import type { BasePaginatorRequest, BasePaginatorResponse } from '@/models/base'
import type { ChatAttachment } from '@/models/upload-file'

// 获取辅助Agent会话消息分页列表请求结构
export type GetAssistantAgentMessagesWithPageRequest = BasePaginatorRequest & {
  created_at?: number
}

// 获取辅助Agent会话消息分页列表响应结构
export type GetAssistantAgentMessagesWithPageResponse = BasePaginatorResponse<{
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
  // 随本条消息上传的附件(服务端已持久化，历史与新消息都会回传)
  attachments?: ChatAttachment[]
  created_at: number
}>
