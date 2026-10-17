import { apiPrefix } from '@/config'

// ============================================================================
// 开放 API Playground —— 端点元数据
// 这是全项目唯一「认识端点」的地方：表单、等价 curl、「快速开始」文档示例都由它生成。
// 新增一个端点，只需要在 openAPIEndpoints 里加一条数据，无需改任何组件。
// ============================================================================

/** 单个请求字段的描述 */
export interface EndpointField {
  /** 字段名，与后端 schema 保持一致 */
  name: string
  /** 展示用中文名 */
  label: string
  /** 位置：header 不进 body；path 用于替换路径占位符 */
  in: 'body' | 'path' | 'header'
  type: 'string' | 'boolean' | 'enum'
  required: boolean
  defaultValue?: string | boolean
  placeholder?: string
  /** 字段下方的说明文字 */
  tip?: string
  /** 动态选项来源，对应页面注册的 loader */
  optionSource?: 'apps' | 'apiKeys'
  /** 仅当另一字段等于指定值时展示 */
  showWhen?: { field: string; equals: unknown }
}

/** 一个开放 API 端点的完整描述（只描述请求侧，响应示例属文档内容） */
export interface OpenAPIEndpoint {
  key: string
  title: string
  method: 'POST'
  /** 支持 {name} 形式的路径占位符 */
  path: string
  /** 该字段的值用于拼 Authorization: Bearer，不进入 body */
  credentialField: string
  /** 该字段为 true 时按 SSE 消费，否则读普通 JSON */
  streamField?: string
  fields: EndpointField[]
  /** 用于生成 curl / 文档示例 */
  sample: Record<string, unknown>
}

/** 参与 UUID 校验的字段名（与后端 schema 的 UUID 字段对齐） */
export const UUID_FIELDS = ['app_id', 'end_user_id', 'conversation_id', 'task_id']

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export const openAPIEndpoints: OpenAPIEndpoint[] = [
  {
    key: 'chat',
    title: 'Chat 对话',
    method: 'POST',
    path: '/openapi/chat',
    credentialField: 'api_key',
    streamField: 'stream',
    fields: [
      {
        name: 'api_key',
        label: 'API Key',
        in: 'header',
        type: 'enum',
        required: true,
        optionSource: 'apiKeys',
        placeholder: 'llmops-v1/... 或手动粘贴',
        tip: '仅用于拼装 Authorization 头，不会进入请求体，也不回传后端',
      },
      {
        name: 'app_id',
        label: '应用',
        in: 'body',
        type: 'enum',
        required: true,
        optionSource: 'apps',
        tip: '仅能调用「已发布」的应用，未发布会返回对应错误码',
      },
      {
        name: 'query',
        label: '用户提问',
        in: 'body',
        type: 'string',
        required: true,
        placeholder: '例如：帮我查询广州今天的天气',
        tip: '不能为空；对话内容会作为该应用的输入',
      },
      {
        name: 'stream',
        label: '流式响应',
        in: 'body',
        type: 'boolean',
        required: false,
        defaultValue: true,
        tip: '开启后按 SSE 逐事件返回（可看推理过程），关闭则一次性返回 JSON',
      },
    ],
    sample: {
      app_id: '<app_id>',
      query: '帮我查询广州今天的天气',
      stream: true,
    },
  },
  {
    key: 'stopChat',
    title: '停止对话',
    method: 'POST',
    path: '/openapi/chat/tasks/{task_id}/stop',
    credentialField: 'api_key',
    fields: [
      {
        name: 'api_key',
        label: 'API Key',
        in: 'header',
        type: 'enum',
        required: true,
        optionSource: 'apiKeys',
        tip: '与「Chat 对话」共用同一份选中值，停止操作本身也需要完整的 Key 鉴权',
      },
      {
        name: 'task_id',
        label: '任务 ID',
        in: 'path',
        type: 'string',
        required: true,
        tip: '流式对话开始后自动填充（每个流式事件都带 task_id）',
      },
    ],
    sample: {
      task_id: '<task_id>',
    },
  },
]

/** 组装后的请求（url 不含 apiPrefix 前缀） */
export interface BuiltRequest {
  url: string
  headers: Record<string, string>
  body: Record<string, any>
  credential: string
}

/**
 * 元数据 + 表单值 → 真实请求
 * @param extraBody 元数据之外的附加 body 字段（如会话状态 conversation_id / end_user_id）
 */
export const buildRequest = (
  endpoint: OpenAPIEndpoint,
  values: Record<string, any>,
  extraBody: Record<string, any> = {},
): BuiltRequest => {
  // 1.替换路径占位符，如 /openapi/chat/tasks/{task_id}/stop
  const url = endpoint.path.replace(/\{(\w+)\}/g, (_match, name: string) => {
    const value = values[name]
    return value === undefined || value === null || value === '' ? '' : encodeURIComponent(String(value))
  })

  // 2.提取凭证字段的值
  const credential = String(values[endpoint.credentialField] ?? '')

  // 3.组装请求体：只放 in === 'body' 的字段，跳过空串 / null / undefined
  const body: Record<string, any> = {}
  endpoint.fields.forEach((field) => {
    if (field.in !== 'body') return
    const value = values[field.name]
    if (value === undefined || value === null || value === '') return
    body[field.name] = value
  })

  // 4.合并附加字段（会话状态），同样跳过空值
  Object.keys(extraBody).forEach((key) => {
    const value = extraBody[key]
    if (value === undefined || value === null || value === '') return
    body[key] = value
  })

  return {
    url,
    headers: {
      Authorization: `Bearer ${credential}`,
      'Content-Type': 'application/json',
    },
    body,
    credential,
  }
}

/** 遮蔽凭证，用于页面展示（复制时用完整版） */
export const maskCredential = (value: string): string => {
  const raw = value.replace(/^Bearer\s+/, '')
  if (raw === '') return ''
  if (raw.length <= 12) return `${raw.slice(0, 4)}****`
  return `${raw.slice(0, 12)}****`
}

/**
 * 元数据 + 表单值 → 等价 curl 命令
 * 该命令可原样粘贴到终端执行
 */
export const buildCurl = (
  endpoint: OpenAPIEndpoint,
  values: Record<string, any>,
  options: {
    origin?: string
    maskCredential?: boolean
    extraBody?: Record<string, any>
  } = {},
): string => {
  const { url, headers, body } = buildRequest(endpoint, values, options.extraBody)
  const origin =
    options.origin ?? (typeof window !== 'undefined' ? window.location.origin : 'http://localhost')
  // dev 环境下 apiPrefix 可能是绝对地址（http://localhost:5001），此时不能再拼 origin
  const prefix = apiPrefix.replace(/\/$/, '')
  const fullUrl = /^https?:\/\//i.test(prefix) ? `${prefix}${url}` : `${origin}${prefix}${url}`
  const authValue = options.maskCredential
    ? `Bearer ${maskCredential(headers.Authorization)}`
    : headers.Authorization

  // curl 的单引号包裹：把内部的单引号转义掉，避免命令被截断
  const quote = (text: string) => `'${text.replace(/'/g, "'\\''")}'`
  const lines = [
    `curl --location --request ${endpoint.method} ${quote(fullUrl)} \\`,
    `--header ${quote(`Authorization: ${authValue}`)} \\`,
    `--header ${quote('Content-Type: application/json')} \\`,
    `--data-raw ${quote(JSON.stringify(body, null, 4))}`,
  ]

  return lines.join('\n')
}

/**
 * 发送前的本地预检：必填 + UUID 格式，与后端 schema 对齐
 * 返回字段名 → 错误信息的映射，空对象表示通过
 */
export const validateValues = (
  endpoint: OpenAPIEndpoint,
  values: Record<string, any>,
): Record<string, string> => {
  const errors: Record<string, string> = {}

  endpoint.fields.forEach((field) => {
    const value = values[field.name]
    const isEmpty = value === undefined || value === null || value === ''

    if (field.required && isEmpty) {
      errors[field.name] = `请填写${field.label}`
      return
    }

    if (!isEmpty && UUID_FIELDS.includes(field.name) && !UUID_RE.test(String(value))) {
      errors[field.name] = `${field.label}格式不正确，应为标准 UUID`
    }
  })

  return errors
}

/** 按 key 取端点，供页面切换时使用 */
export const getEndpoint = (key: string): OpenAPIEndpoint | undefined =>
  openAPIEndpoints.find((endpoint) => endpoint.key === key)
