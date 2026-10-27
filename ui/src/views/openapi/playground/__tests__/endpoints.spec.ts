import { afterEach, describe, expect, it, vi } from 'vitest'

import { buildRequest, getEndpoint, openAPIEndpoints, validateValues } from '../endpoints'

// ============================================================================
// 端点元数据是「单一数据源」：表单、等价 curl、文档示例都由它生成。
// 这里只测纯函数，保证这份数据派生出来的请求是对的。
// ============================================================================

const chat = getEndpoint('chat')!
const stopChat = getEndpoint('stopChat')!

const TASK_ID = '03042ead-23d6-42c6-a5c9-caac416bb80c'
const APP_ID = '11356d51-7047-4668-9a7a-5fb6eb27e032'

/**
 * buildCurl 的 URL 前缀来自 config/index.ts 的模块级常量（导入时读取 VITE_API_PREFIX），
 * 所以必须先 stub 环境变量再动态导入，才能得到确定的断言结果。
 */
const importBuildCurl = async (prefix: string) => {
  vi.resetModules()
  vi.stubEnv('VITE_API_PREFIX', prefix)
  const mod = await import('../endpoints')
  return mod.buildCurl
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('buildRequest —— 元数据到请求的组装', () => {
  it('header 字段不进 body，body 只放 in=body 的字段', () => {
    const built = buildRequest(chat, {
      api_key: 'llmops-v1/abc',
      app_id: APP_ID,
      query: '你好',
      stream: false,
    })

    expect(built.url).toBe('/openapi/chat')
    expect(built.body).toEqual({ app_id: APP_ID, query: '你好', stream: false })
    expect(built.credential).toBe('llmops-v1/abc')
    expect(built.headers.Authorization).toBe('Bearer llmops-v1/abc')
    expect(built.headers['Content-Type']).toBe('application/json')
  })

  it('空串 / null / undefined 的字段被跳过（例如关闭流式时传空串）', () => {
    const built = buildRequest(chat, { api_key: 'k', app_id: APP_ID, query: '', stream: null })

    expect(built.body).toEqual({ app_id: APP_ID })
  })

  it('extraBody（会话状态）合并进 body，且同样跳过空值', () => {
    const built = buildRequest(
      chat,
      { api_key: 'k', app_id: APP_ID, query: 'hi' },
      { conversation_id: '11356d51-7047-4668-9a7a-5fb6eb27e032', end_user_id: '' },
    )

    expect(built.body).toEqual({
      app_id: APP_ID,
      query: 'hi',
      conversation_id: '11356d51-7047-4668-9a7a-5fb6eb27e032',
    })
  })

  it('路径占位符被替换并做 URL 编码', () => {
    const built = buildRequest(stopChat, { api_key: 'k', task_id: TASK_ID })

    expect(built.url).toBe(`/openapi/chat/tasks/${TASK_ID}/stop`)
    // 停止端点没有 body 字段
    expect(built.body).toEqual({})
    expect(built.headers.Authorization).toBe('Bearer k')
  })

  it('占位符缺值时替换为空串（必填校验由 validateValues 前置拦截，不会真发出请求）', () => {
    const built = buildRequest(stopChat, { api_key: 'k' })

    expect(built.url).toBe('/openapi/chat/tasks//stop')
  })

  it('空附件数组被跳过：不带附件时 body 不出现 files 字段', () => {
    const built = buildRequest(chat, { api_key: 'k', app_id: APP_ID, query: 'hi', files: [] })

    expect(built.body).toEqual({ app_id: APP_ID, query: 'hi' })
    expect(built.body.files).toBeUndefined()
  })

  it('带附件时 files 原样进入 body', () => {
    const files = [{ name: '报告.pdf', kind: 'text', text: '正文' }]
    const built = buildRequest(chat, { api_key: 'k', app_id: APP_ID, query: 'hi', files })

    expect(built.body.files).toEqual(files)
  })
})

describe('buildCurl —— 元数据到等价 curl', () => {
  it('拼出 origin + apiPrefix + path 的完整地址，Key 默认不遮蔽', async () => {
    const buildCurl = await importBuildCurl('/api')

    const curl = buildCurl(
      chat,
      { api_key: 'llmops-v1/supersecretkey', app_id: APP_ID, query: 'hi', stream: true },
      { origin: 'https://play.example.com' },
    )

    expect(curl).toContain(`--request POST 'https://play.example.com/api/openapi/chat'`)
    expect(curl).toContain(`--header 'Authorization: Bearer llmops-v1/supersecretkey'`)
    expect(curl).toContain(`--header 'Content-Type: application/json'`)
    // body 用 JSON.stringify(body, null, 4) 排版，且不含 header 字段
    expect(curl).toContain('"app_id": ' + JSON.stringify(APP_ID))
    expect(curl).not.toContain('"api_key"')
  })

  it('maskCredential 打开时只展示前缀', async () => {
    const buildCurl = await importBuildCurl('/api')

    const curl = buildCurl(
      chat,
      { api_key: 'llmops-v1/supersecretkey', app_id: APP_ID, query: 'hi' },
      { origin: 'https://play.example.com', maskCredential: true },
    )

    expect(curl).toContain(`--header 'Authorization: Bearer llmops-v1/su****'`)
    expect(curl).not.toContain('supersecretkey')
  })

  it('collapseAttachments 只影响展示，完整版仍带附件正文全文', async () => {
    const buildCurl = await importBuildCurl('/api')
    const longText = 'x'.repeat(500)
    const values = {
      api_key: 'k',
      app_id: APP_ID,
      query: 'hi',
      files: [{ name: 'a.txt', kind: 'text', text: longText }],
    }

    const collapsed = buildCurl(chat, values, {
      origin: 'https://play.example.com',
      collapseAttachments: true,
    })
    const full = buildCurl(chat, values, { origin: 'https://play.example.com' })

    expect(collapsed).toContain('此处为面板预览')
    expect(full).not.toContain('此处为面板预览')
    expect(full).toContain(longText)
    // 折叠是深拷贝，不能污染原始表单值
    expect(values.files[0].text).toHaveLength(500)
  })

  it('apiPrefix 是绝对地址时不再拼 origin（dev 直连后端的情形）', async () => {
    const buildCurl = await importBuildCurl('http://localhost:5001')

    const curl = buildCurl(
      chat,
      { api_key: 'k', app_id: APP_ID, query: 'hi' },
      { origin: 'https://play.example.com' },
    )

    expect(curl).toContain(`--request POST 'http://localhost:5001/openapi/chat'`)
  })
})

describe('validateValues —— 与后端 schema 对齐的前置校验', () => {
  it('必填缺失逐字段报错', () => {
    expect(validateValues(chat, {})).toEqual({
      api_key: '请填写API Key',
      app_id: '请填写应用',
      query: '请填写用户提问',
    })
  })

  it('UUID 字段格式不对时报错', () => {
    const errors = validateValues(chat, { api_key: 'k', app_id: 'not-a-uuid', query: 'hi' })

    expect(errors).toEqual({ app_id: '应用格式不正确，应为标准 UUID' })
  })

  it('参数齐备且格式正确时通过', () => {
    const errors = validateValues(chat, { api_key: 'k', app_id: APP_ID, query: 'hi' })

    expect(errors).toEqual({})
  })

  it('path 参数同样按 UUID 校验（后端路由是 <uuid:task_id>，格式不符会 404）', () => {
    expect(validateValues(stopChat, { api_key: 'k', task_id: '随便写的' })).toEqual({
      task_id: '任务 ID格式不正确，应为标准 UUID',
    })
    expect(validateValues(stopChat, { api_key: 'k', task_id: TASK_ID })).toEqual({})
  })
})

describe('元数据自洽', () => {
  it('credentialField / 路径占位符 / sample 都能在 fields 里找到', () => {
    openAPIEndpoints.forEach((endpoint) => {
      const names = endpoint.fields.map((field) => field.name)

      expect(names).toContain(endpoint.credentialField)

      const placeholders = [...endpoint.path.matchAll(/\{(\w+)\}/g)].map((match) => match[1])
      placeholders.forEach((name) => expect(names).toContain(name))

      Object.keys(endpoint.sample).forEach((name) => expect(names).toContain(name))
    })
  })

  it('每个端点都声明了 auth 字段为 header 位置（凭证绝不进 body）', () => {
    openAPIEndpoints.forEach((endpoint) => {
      const credential = endpoint.fields.find((field) => field.name === endpoint.credentialField)

      expect(credential?.in).toBe('header')
      expect(credential?.required).toBe(true)
    })
  })
})
