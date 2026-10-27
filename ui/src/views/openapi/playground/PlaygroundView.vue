<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { QueueEvent, httpCode } from '@/config'
import { getAppsWithPage } from '@/services/app'
import { getApiKeysWithPage } from '@/services/api-key'
import { requestOpenAPI, stopOpenAPIChat, type OpenAPIResult } from '@/services/openapi-playground'
import {
  buildCurl,
  getEndpoint,
  openAPIEndpoints,
  validateValues,
  type OpenAPIEndpoint,
} from './endpoints'
import RequestForm from './components/RequestForm.vue'
import ResponsePanel from './components/ResponsePanel.vue'

// ============================================================================
// 页面：开放 API Playground
// 左侧表单由端点元数据驱动，右侧同时给出「回答 / 原始事件流 / 等价 curl」
// 关键约束：这里所有业务请求只带 API Key，绝不注入登录态 access_token
// ============================================================================

// 1.端点切换
const activeKey = ref(openAPIEndpoints[0]?.key ?? 'chat')
const endpoint = computed<OpenAPIEndpoint | undefined>(() => getEndpoint(activeKey.value))

// 2.表单值 —— 跨端点统一维护，同名共用字段（api_key）切换端点时不丢
const values = reactive<Record<string, any>>({})
const errors = ref<Record<string, string>>({})

// 初始化所有端点的字段默认值
openAPIEndpoints.forEach((ep) => {
  ep.fields.forEach((field) => {
    if (values[field.name] === undefined) {
      // 附件字段的初值必须是空数组：空数组在 buildRequest 里会被跳过，等价于「不传该字段」
      values[field.name] = field.type === 'files'
        ? []
        : field.defaultValue ?? (field.type === 'boolean' ? false : '')
    }
  })
})

// 3.动态选项：应用 / API 秘钥，走平台自身的鉴权接口（带 access_token）
const options = reactive<{
  apps: { value: string; label: string }[]
  apiKeys: { value: string; label: string }[]
}>({ apps: [], apiKeys: [] })

const loadOptions = async () => {
  // 注意：后端 PaginatorReq 限制 page_size ∈ [1, 50]，
  // 传 100 会被 wtforms 直接判为 validate_error，两个列表都会返回「每页数据的条数范围在1-50」
  const [appsResult, keysResult] = await Promise.allSettled([
    getAppsWithPage({ current_page: 1, page_size: 50, search_word: '' }),
    getApiKeysWithPage({ current_page: 1, page_size: 50 }),
  ])

  if (appsResult.status === 'fulfilled') {
    options.apps = (appsResult.value.data?.list ?? []).map((app: any) => ({
      value: app.id,
      label: app.status === 'published' ? app.name : `${app.name}（未发布，调用会失败）`,
    }))
  } else {
    Message.error('应用列表加载失败，可手动粘贴 app_id 后继续')
  }

  if (keysResult.status === 'fulfilled') {
    // 仅列出已启用的秘钥：停用的 Key 调用必然失败，列出来只会误导
    options.apiKeys = (keysResult.value.data?.list ?? [])
      .filter((item: any) => item.is_active)
      .map((item: any) => ({
        value: item.api_key,
        label: `${item.remark || '未命名秘钥'}（${String(item.api_key).slice(0, 12)}…）`,
      }))
  } else {
    Message.error('API 秘钥加载失败，可手动粘贴 API Key 后继续')
  }
}

onMounted(loadOptions)

// 4.会话状态：全部由服务端回带，用于多轮对话与停止
const session = reactive({ task_id: '', conversation_id: '', end_user_id: '' })

// 5.响应状态
const answer = ref('')
const thoughts = ref<any[]>([])
const rawStream = ref('')
const errorText = ref('')
const loading = ref(false)
const stopping = ref(false)
let abortController: AbortController | null = null

// 6.会话状态只在「Chat 对话」这类有流式的端点上作为附加 body 发送
const extraBody = (ep: OpenAPIEndpoint) => {
  if (ep.streamField === undefined) return {}
  return {
    conversation_id: session.conversation_id,
    end_user_id: session.end_user_id,
  }
}

// 7.等价 curl：默认遮蔽凭证，复制时给完整版
// 附件正文可能上万字符，面板默认折叠成预览；勾选「展开附件内容」才显示全文
const expandAttachments = ref(false)
const curlText = computed(() =>
  endpoint.value
    ? buildCurl(endpoint.value, values, {
        maskCredential: true,
        extraBody: extraBody(endpoint.value),
        collapseAttachments: !expandAttachments.value,
      })
    : '',
)
// 复制走这个版本：凭证完整、附件正文也完整，保证命令粘贴到终端可以直接执行
const curlFullText = computed(() =>
  endpoint.value
    ? buildCurl(endpoint.value, values, {
        maskCredential: false,
        extraBody: extraBody(endpoint.value),
      })
    : '',
)

const resetOutput = () => {
  answer.value = ''
  thoughts.value = []
  rawStream.value = ''
  errorText.value = ''
}

// 切换端点时清空右侧输出，但保留左侧表单值
watch(activeKey, () => {
  errors.value = {}
  resetOutput()
})

// 8.处理单帧 SSE 事件
const handleEvent = (payload: { event: string; data: Record<string, any> }) => {
  const { event, data } = payload

  // 8.1 每帧都带 task_id / conversation_id / end_user_id，取到即记录
  if (data?.task_id && session.task_id === '') {
    session.task_id = String(data.task_id)
    // 同步到表单，供「停止对话」端点的路径参数使用
    values.task_id = String(data.task_id)
  }
  if (data?.conversation_id && session.conversation_id === '') {
    session.conversation_id = String(data.conversation_id)
  }
  if (data?.end_user_id && session.end_user_id === '') {
    session.end_user_id = String(data.end_user_id)
  }

  // 8.2 回答是逐 token 增量，需要累加，且不进推理链路
  if (event === QueueEvent.agentMessage) {
    answer.value += data?.answer ?? ''
    return
  }

  // 8.3 ping 只是心跳，不展示
  if (event === QueueEvent.ping) return

  // 8.4 其余事件进入推理链路
  thoughts.value.push(data)

  // 8.5 错误事件把观测原文交出来
  if (event === QueueEvent.error) {
    errorText.value = String(data?.observation ?? data?.raw ?? '服务端返回了 error 事件')
  }
}

// 9.处理非流式 / JSON 响应
const handleNonStreamResult = (result: OpenAPIResult) => {
  // 主动中断属于正常流程
  if (result.aborted) return

  // 非 JSON（含流式全文）：分片已在回调里累积，这里只做兜底
  if (result.parsed === undefined) {
    if (result.raw && rawStream.value === '') rawStream.value = result.raw
    return
  }

  const parsed: any = result.parsed

  if (parsed?.code === httpCode.success) {
    if (parsed.data?.answer !== undefined) answer.value = String(parsed.data.answer)
    if (parsed.data?.conversation_id) session.conversation_id = String(parsed.data.conversation_id)
    if (parsed.data?.end_user_id) session.end_user_id = String(parsed.data.end_user_id)
    return
  }

  // 业务错误：HTTP 200 也可能失败，原文必须完整展示，不能只弹一个 toast
  errorText.value = result.raw || JSON.stringify(parsed)
  if (parsed?.code === httpCode.unauthorized) {
    Message.warning('API Key 无效或已停用，请到「API 秘钥」页确认后重新选择')
  }
}

// 10.发送请求
const handleSend = async () => {
  const current = endpoint.value
  if (!current) return

  // 10.1 本地预检：与后端 schema 对齐，避免把错误请求发出去
  errors.value = validateValues(current, values)
  if (Object.keys(errors.value).length > 0) {
    Message.warning('请先修正表单中的错误')
    return
  }

  // 10.2 重置输出与会话（每次发送都是一次全新调用）
  resetOutput()
  session.task_id = ''
  loading.value = true
  abortController = new AbortController()

  try {
    const result = await requestOpenAPI(
      current,
      values,
      {
        onEvent: handleEvent,
        onRawChunk: (text) => {
          rawStream.value += text
        },
      },
      abortController.signal,
      extraBody(current),
    )

    handleNonStreamResult(result)
  } catch (error: any) {
    // 10.3 请求没到后端（跨域 / 服务未启动）：给出可自查的原文
    errorText.value = [
      `请求未送达后端：${error?.message ?? error}`,
      '',
      '自查顺序：',
      '1) 后端容器是否已启动（docker ps 看 llmops-api）；',
      '2) 重建 api 后是否重启过 nginx（否则 502）；',
      '3) 浏览器控制台是否有 CORS 报错。',
    ].join('\n')
  } finally {
    loading.value = false
    abortController = null
  }
}

// 11.停止响应
const handleStop = async () => {
  const stopEndpoint = getEndpoint('stopChat')
  if (!stopEndpoint) return

  if (session.task_id === '') {
    Message.warning('尚未拿到 task_id，无法停止（请先发起一次流式对话）')
    return
  }

  stopping.value = true
  try {
    const result = await stopOpenAPIChat(stopEndpoint, {
      api_key: values.api_key,
      task_id: session.task_id,
    })

    if (result.parsed?.code === httpCode.success) {
      Message.success('已发送停止指令，流式输出将很快结束')
      return
    }

    // 停止指令没生效（如归属校验失败）：本地断开兜底，至少让页面不再空等
    abortController?.abort()
    Message.error(`停止指令未生效，已本地断开连接。服务端返回：${result.raw}`)
  } catch (error: any) {
    abortController?.abort()
    Message.error(`停止请求失败，已本地断开连接：${error?.message ?? error}`)
  } finally {
    stopping.value = false
  }
}

// 12.清空会话
const handleClearSession = () => {
  session.task_id = ''
  session.conversation_id = ''
  session.end_user_id = ''
  values.task_id = ''
  Message.success('会话状态已清空，下次请求将作为新会话')
}
</script>

<template>
  <div class="flex min-h-0 flex-1 flex-col gap-4 pb-6">
    <!-- 页头 -->
    <div class="flex items-start justify-between gap-4">
      <div>
        <h2 class="text-lg font-medium text-gray-900">Playground</h2>
        <p class="mt-1 text-sm text-gray-500">
          不用写代码就能调通开放 API。这里的业务请求<b>只带下方所选的 API Key、不带你的登录态</b>，
          因此页面结果与第三方真实调用完全一致。
          例外是<b>附件上传</b>：文件由平台上传解析（走你的登录态），再作为 <code class="text-xs">files</code>
          随请求发出；第三方调用需自备 <code class="text-xs">text</code> 正文或可公开访问的
          <code class="text-xs">url</code>。
        </p>
      </div>
      <router-link to="/openapi/api-keys" class="flex-shrink-0">
        <a-button type="text">管理 API 秘钥</a-button>
      </router-link>
    </div>

    <!-- 端点切换 -->
    <div class="flex items-center gap-3">
      <a-radio-group v-model="activeKey" type="button">
        <a-radio v-for="ep in openAPIEndpoints" :key="ep.key" :value="ep.key">
          {{ ep.title }}
        </a-radio>
      </a-radio-group>
      <a-tag color="arcoblue">{{ endpoint?.method }} {{ endpoint?.path }}</a-tag>
    </div>

    <!-- 主体：左表单 / 右响应 -->
    <div
      class="grid flex-1 grid-cols-1 grid-rows-[minmax(0,1fr)] gap-4 overflow-hidden lg:grid-cols-[minmax(340px,420px)_1fr]"
    >
      <a-card class="!h-full !min-h-0 overflow-auto" :bordered="false">
        <RequestForm
          v-if="endpoint"
          :endpoint="endpoint"
          :values="values"
          :errors="errors"
          :options="options"
          :session="session"
          :loading="loading"
          :stopping="stopping"
          @update:values="(next) => Object.assign(values, next)"
          @send="handleSend"
          @stop="handleStop"
          @clear-session="handleClearSession"
        />
      </a-card>

      <a-card class="panel-card" :bordered="false">
        <ResponsePanel
          :answer="answer"
          :thoughts="thoughts"
          :raw-stream="rawStream"
          :curl="curlText"
          :curl-full="curlFullText"
          :error="errorText"
          :loading="loading"
          v-model:expand-attachments="expandAttachments"
          @clear-raw="rawStream = ''"
        />
      </a-card>
    </div>
  </div>
</template>

<style scoped>
/* 右侧卡片：把高度链打通，让内部面板能真正滚动，而不是被卡片裁掉 */
.panel-card {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

.panel-card :deep(.arco-card-body) {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
</style>
