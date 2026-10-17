import { apiPrefix } from '@/config'
import { buildRequest, type OpenAPIEndpoint } from '@/views/openapi/playground/endpoints'

// ============================================================================
// 开放 API Playground 的直连封装
//
// 刻意不复用 utils/request.ts，原因（均已逐行核对）：
// 1. ssePost 会无条件写入 access_token，顶掉 API Key —— 开放 API 只认 API Key，
//    带上登录态 JWT 会被后端拿去查 api_keys 表，必然报「该秘钥不存在或未激活」；
// 2. baseFetch 在 code === 'unauthorized' 时会清凭证并跳登录页，而这里的 unauthorized
//    只代表「这个 Key 不行」，不该影响当前登录态；
// 3. 排障需要原始 SSE 文本，而 handleStream 只回调解析后的 {event, data}；
// 4. request.ts 的 headers 是模块级单例，复用会互相污染。
//
// 约定：列表类接口（应用 / 秘钥）仍走 utils/request.ts（带 access_token），
//       业务请求走这里（只带 API Key）。两套凭证严禁混用。
// ============================================================================

export interface OpenAPIEventPayload {
  event: string
  data: Record<string, any>
}

export interface OpenAPIResult {
  ok: boolean
  status: number
  contentType: string
  /** 原始响应文本：SSE 为全文，JSON 为原文，非 JSON 响应也如实保留 */
  raw: string
  /** 仅当响应是 JSON 时存在（含 HTTP 200 的业务错误） */
  parsed?: any
  /** 是否由调用方主动中断（AbortController） */
  aborted?: boolean
}

export interface OpenAPICallbacks {
  /** 每解析出一帧 SSE 事件回调一次 */
  onEvent?: (payload: OpenAPIEventPayload) => void
  /** 每收到一段原始文本就回调一次，用于「原始事件流」视图 */
  onRawChunk?: (text: string) => void
}

/**
 * 消费 SSE 响应：逐帧解析并同时回调「解析后事件」与「原始文本」
 * 分帧方式沿用项目既有做法（按行判断空行结束），保证与后端输出格式一致
 */
const consumeStream = (response: Response, callbacks: OpenAPICallbacks): Promise<OpenAPIResult> => {
  return new Promise((resolve, reject) => {
    const reader = response.body?.getReader()
    if (!reader) {
      reject(new Error('当前环境不支持流式读取响应'))
      return
    }

    const decoder = new TextDecoder('utf-8')
    let raw = ''
    let buffer = ''
    let event = ''
    let data = ''

    const read = () => {
      reader
        .read()
        .then((result) => {
          // 1.流结束，返回完整原始文本
          if (result.done) {
            resolve({
              ok: response.ok,
              status: response.status,
              contentType: response.headers.get('Content-Type') ?? '',
              raw,
            })
            return
          }

          // 2.解码并累积原始文本
          const text = decoder.decode(result.value, { stream: true })
          raw += text
          callbacks.onRawChunk?.(text)

          // 3.按行切分，逐个事件处理
          buffer += text
          const lines = buffer.split('\n')
          lines.forEach((line) => {
            const trimmed = line.trim()
            if (trimmed.startsWith('event:')) {
              event = trimmed.slice(6).trim()
            } else if (trimmed.startsWith('data:')) {
              data = trimmed.slice(5).trim()
            }

            // 4.空行表示一帧结束，event 与 data 都拿到才算完整
            if (trimmed === '' && event !== '' && data !== '') {
              try {
                callbacks.onEvent?.({ event, data: JSON.parse(data) })
              } catch {
                // 5.单帧解析失败不能中断整条流，如实把原文交出去
                callbacks.onEvent?.({ event, data: { raw: data } })
              }
              event = ''
              data = ''
            }
          })
          buffer = lines.pop() ?? ''

          read()
        })
        .catch(reject)
    }

    read()
  })
}

/**
 * 发起一次开放 API 请求
 * @param signal 用于「本地断开」兜底（停止响应超时未生效时使用）
 */
export const requestOpenAPI = async (
  endpoint: OpenAPIEndpoint,
  values: Record<string, any>,
  callbacks: OpenAPICallbacks = {},
  signal?: AbortSignal,
  extraBody: Record<string, any> = {},
): Promise<OpenAPIResult> => {
  const { url, headers, body } = buildRequest(endpoint, values, extraBody)

  let response: Response
  try {
    response = await globalThis.fetch(`${apiPrefix}${url}`, {
      method: endpoint.method,
      headers,
      body: JSON.stringify(body),
      // 真实第三方调用方不会携带本站 cookie，直连时省略才等价复现对方链路
      credentials: 'omit',
      mode: 'cors',
      redirect: 'follow',
      signal,
    })
  } catch (error: any) {
    // AbortController 主动中断属于正常流程，不当作错误抛出
    if (signal?.aborted || error?.name === 'AbortError') {
      return { ok: false, status: 0, contentType: '', raw: '', aborted: true }
    }
    throw error
  }

  const contentType = response.headers.get('Content-Type') ?? ''

  // 1.流式响应（后端出错时会退化成 application/json，故先判断 json）
  if (!contentType.includes('application/json') && response.body) {
    return await consumeStream(response, callbacks)
  }

  // 2.JSON 响应：可能是成功，也可能是 HTTP 200 包装的业务错误
  const raw = await response.text()
  callbacks.onRawChunk?.(raw)

  let parsed: any
  try {
    parsed = JSON.parse(raw)
  } catch {
    // 3.非 JSON（如网关 / 代理返回的 HTML 错误页），保留原文交由页面展示
    parsed = undefined
  }

  return { ok: response.ok, status: response.status, contentType, raw, parsed }
}

/** 停止开放 API 会话（本质也是开放 API 端点，仍带 API Key 鉴权） */
export const stopOpenAPIChat = async (
  endpoint: OpenAPIEndpoint,
  values: Record<string, any>,
): Promise<OpenAPIResult> => {
  const { url, headers, body } = buildRequest(endpoint, values)
  const response = await globalThis.fetch(`${apiPrefix}${url}`, {
    method: endpoint.method,
    headers,
    body: JSON.stringify(body),
    credentials: 'omit',
    mode: 'cors',
  })
  const raw = await response.text()

  let parsed: any
  try {
    parsed = JSON.parse(raw)
  } catch {
    parsed = undefined
  }

  return {
    ok: response.ok,
    status: response.status,
    contentType: response.headers.get('Content-Type') ?? '',
    raw,
    parsed,
  }
}
