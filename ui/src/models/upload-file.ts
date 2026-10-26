import { type BaseResponse } from '@/models/base'

// 上传图片响应结构
export type UploadImageResponse = BaseResponse<{
  image_url: string
}>

// 上传文件响应结构
export type UploadFileResponse = BaseResponse<{
  id: string
  account_id: string
  name: string
  key: string
  size: number
  extension: string
  mime_type: string
  created_at: number
}>

// 对话附件类型：text=解析出文本、image=图片、file=其它二进制文件
export type ChatAttachmentKind = 'text' | 'image' | 'file'

// 对话附件结构(随消息提交给大模型：有text注入文本，无text注入文件地址以支持多模态)
export type ChatAttachment = {
  // 附件文件名
  name: string
  // 附件扩展名
  extension: string
  // 附件字节大小
  size: number
  // 附件类型
  kind: ChatAttachmentKind
  // 服务端解析出的文本内容(图片/二进制文件为空；历史消息回传时不携带该字段)
  text?: string
  // 附件的可访问地址(图片与二进制文件返回，文本类附件为空)
  url?: string
  // 附件MIME类型
  mime?: string
  // 文本是否被截断
  truncated?: boolean
  // 服务端返回的补充说明(例如图片未解析出文本、解析失败已降级为文件)
  note?: string
}

// 上传对话附件响应结构
export type UploadFileTextResponse = BaseResponse<ChatAttachment>
