<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { uploadFileText } from '@/services/upload-file'
import type { ChatAttachment, ChatAttachmentKind } from '@/models/upload-file'
import { useAudioToText, useSpeechEngine } from '@/hooks/use-audio'

// 1.定义组件所需数据
const props = defineProps({
  // 是否正在请求大模型(请求中禁止重复提交)
  loading: { type: Boolean, default: false },
  // 输入框占位提示
  placeholder: { type: String, default: '输入消息' },
  // 单次最多携带的附件数量
  max_files: { type: Number, default: 5 },
  // 单个附件最大体积(默认30MB，与服务端限制保持一致)
  max_size: { type: Number, default: 30 * 1024 * 1024 },
  // 允许上传的附件格式(默认不限制，任意文件都可以作为附件)
  accept: { type: String, default: '' },
})
const emits = defineEmits<{
  (e: 'submit', payload: { query: string; attachments: ChatAttachment[] }): void
}>()

// 2.定义组件内部状态(附件项在ChatAttachment基础上增加本地uid与上传状态)
type AttachmentItem = ChatAttachment & {
  uid: string
  uploading: boolean
}

const query = ref('')
const attachments = ref<AttachmentItem[]>([])
const recording = ref(false)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

// 3.计算是否正在解析附件以及发送按钮是否禁用
const uploading = computed(() => attachments.value.some((item) => item.uploading))
const sendDisabled = computed(() => props.loading || uploading.value)
const maxSizeText = computed(() => `${Math.round(props.max_size / 1024 / 1024)}MB`)

// 4.定义输入框自适应高度函数
const autoResize = () => {
  nextTick(() => {
    const textarea = textareaRef.value
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${Math.min(textarea.scrollHeight, 160)}px`
  })
}

// 5.定义回车提交逻辑(回车发送、Shift+回车换行、中文输入法组词时不提交)
const handleKeydown = (event: KeyboardEvent) => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  submit()
}

// 6.定义提交函数，支持直接传入文本(用于点击建议问题直接发送)
const submit = (text?: string) => {
  // 6.1 如果传入了文本则同步到输入框
  if (typeof text === 'string') {
    query.value = text
    autoResize()
  }

  // 6.2 校验提问内容与附件状态
  const humanQuery = query.value.trim()
  if (humanQuery === '') {
    Message.warning('用户提问不能为空')
    return
  }
  if (uploading.value) {
    Message.warning('附件正在处理中，请稍候')
    return
  }
  if (props.loading) {
    Message.warning('上一次提问还未结束，请稍等')
    return
  }

  // 6.3 触发提交事件并清空输入框与附件
  emits('submit', {
    query: humanQuery,
    attachments: attachments.value.map(
      (item) =>
        ({
          name: item.name,
          extension: item.extension,
          size: item.size,
          kind: item.kind,
          text: item.text,
          url: item.url,
          mime: item.mime,
          truncated: item.truncated,
          note: item.note,
        }) as ChatAttachment,
    ),
  })
  query.value = ''
  attachments.value = []
  autoResize()
}

// 7.定义填充与清空方法，供父组件操作输入框
const fill = (text: string) => {
  query.value = text
  autoResize()
}
const clear = () => {
  query.value = ''
  attachments.value = []
  autoResize()
}

// 8.定义附件选择与移除函数
const pickFile = () => {
  if (props.loading) return
  fileInputRef.value?.click()
}

const removeAttachment = (uid: string) => {
  attachments.value = attachments.value.filter((item) => item.uid !== uid)
}

// 8.1 按uid替换数组中的元素(必须替换而不能改局部变量，否则vue不会触发重渲染，
// 表现就是附件一直转圈、发送按钮一直禁用)
const patchAttachment = (uid: string, patch: Partial<AttachmentItem>) => {
  const index = attachments.value.findIndex((item) => item.uid === uid)
  if (index === -1) return
  attachments.value[index] = { ...attachments.value[index], ...patch }
}

const handleFilesChange = async (event: Event) => {
  // 8.2 提取本次选择的文件并重置input(便于重复选择同一文件)
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (files.length === 0) return

  // 8.3 循环处理每个文件：数量、体积、重复校验后逐个上传解析
  for (const file of files) {
    if (attachments.value.length >= props.max_files) {
      Message.warning(`单次最多携带${props.max_files}个附件`)
      break
    }
    if (file.size > props.max_size) {
      Message.warning(`「${file.name}」超过${maxSizeText.value}，已跳过`)
      continue
    }
    if (attachments.value.some((item) => item.name === file.name && item.size === file.size)) {
      Message.warning(`「${file.name}」已添加，请勿重复上传`)
      continue
    }

    // 8.4 先插入占位项展示处理中状态
    const uid = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const extension = file.name.split('.').pop()?.toLowerCase() ?? ''
    const guessingKind: ChatAttachmentKind = file.type.startsWith('image/') ? 'image' : 'text'
    attachments.value.push({
      uid,
      name: file.name,
      extension,
      size: file.size,
      kind: guessingKind,
      text: '',
      mime: file.type,
      uploading: true,
    })

    // 8.5 调用服务端接口处理附件，成功后按uid回写结果，失败则移除占位项并提示
    try {
      const resp = await uploadFileText(file)
      const data = resp?.data
      if (!data) throw new Error('附件处理失败，请重试')
      patchAttachment(uid, {
        name: data.name || file.name,
        extension: data.extension || extension,
        size: data.size || file.size,
        kind: data.kind ?? guessingKind,
        text: data.text ?? '',
        url: data.url || '',
        mime: data.mime || file.type,
        truncated: data.truncated ?? false,
        note: data.note || '',
        uploading: false,
      })
    } catch (error: any) {
      removeAttachment(uid)
      Message.error(error?.message ?? `「${file.name}」处理失败，请重试`)
    }
  }
}

// 9.定义语音输入相关数据与函数
//    CR-16102803：按「设置 → 语音服务」的引擎分派 ——
//      dashscope → 录 16k WAV 上传给服务端识别（Paraformer 不支持 webm，见 D-12）；
//      browser / omni → 沿用浏览器 Web Speech API（omni 档不提供服务端 ASR，见 D-08）。
const { engine, ensure: ensureSpeechEngine } = useSpeechEngine()
const { recorder: wavRecorder, recognize } = useAudioToText()
let recognition: any = null
let recordBase = ''
let recordFinal = ''

// 释放浏览器识别资源
const destroyRecognition = () => {
  if (!recognition) return
  try {
    recognition.onresult = null
    recognition.onend = null
    recognition.onerror = null
    recognition.abort()
  } catch {
    // 忽略停止时的异常
  }
  recognition = null
  recording.value = false
}

// 进入组件时拉一次引擎配置（失败不影响录音，退回浏览器识别）
onMounted(() => {
  ensureSpeechEngine().catch(() => {})
})

// 服务端识别路径：录音 → 上传 → 回填
const toggleServerRecord = async () => {
  if (recording.value) {
    recording.value = false
    const blob = await wavRecorder.stop()
    if (!blob) {
      Message.warning('没有录到声音，请重新说一次')
      return
    }
    try {
      const text = await recognize(blob)
      if (text) {
        query.value = `${query.value}${text}`
        autoResize()
        Message.success('语音转文本成功')
      }
    } catch (error: any) {
      Message.error(error?.message || '语音识别失败，请重试')
    }
    return
  }

  try {
    await wavRecorder.start()
    recording.value = true
    Message.info('正在录音，再次点击结束')
  } catch (error: any) {
    Message.error(error?.message || '无法启动录音')
    recording.value = false
  }
}

// 浏览器识别路径（原逻辑，函数体未改动）
const toggleBrowserRecord = () => {
  // 9.1 正在录音则停止录音
  if (recording.value) {
    destroyRecognition()
    return
  }

  // 9.2 检测浏览器是否支持语音识别
  const SpeechRecognitionClass =
    (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  if (!SpeechRecognitionClass) {
    Message.warning('当前浏览器不支持语音输入，请使用 Chrome 或 Edge 浏览器')
    return
  }

  // 9.3 初始化语音识别对象
  recordBase = query.value
  recordFinal = ''
  recognition = new SpeechRecognitionClass()
  recognition.lang = 'zh-CN'
  recognition.continuous = true
  recognition.interimResults = true

  recognition.onstart = () => {
    recording.value = true
  }

  // 9.4 实时把识别结果写回输入框(最终结果累加，临时结果追加展示)
  recognition.onresult = (event: any) => {
    let interimText = ''
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const transcript = event.results[i][0].transcript
      if (event.results[i].isFinal) {
        recordFinal += transcript
      } else {
        interimText += transcript
      }
    }
    query.value = `${recordBase}${recordFinal}${interimText}`
    autoResize()
  }

  // 9.5 处理结束与异常
  recognition.onend = () => {
    recording.value = false
    query.value = `${recordBase}${recordFinal}`
    autoResize()
  }
  recognition.onerror = (event: any) => {
    recording.value = false
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
      Message.error('麦克风权限被拒绝，请在浏览器中允许使用麦克风')
    } else if (event.error === 'network') {
      Message.error('语音识别服务连接失败，请检查网络后重试')
    } else if (event.error === 'no-speech') {
      Message.warning('没有检测到语音，请重新说一次')
    } else if (event.error !== 'aborted') {
      Message.error('语音识别失败，请重试')
    }
  }

  // 9.6 启动语音识别
  try {
    recognition.start()
  } catch {
    Message.error('语音识别启动失败，请重试')
    destroyRecognition()
  }
}

// 语音输入总入口：按引擎分派（dashscope 走服务端，其余走浏览器）
const toggleRecord = () => {
  if (engine.value === 'dashscope') {
    toggleServerRecord()
    return
  }
  toggleBrowserRecord()
}

// 10.组件卸载时释放语音识别资源
onBeforeUnmount(() => {
  destroyRecognition()
})

// 11.对外暴露方法，供父组件填充文本/直接提交
defineExpose({ submit, fill, clear })
</script>

<template>
  <div class="w-full flex flex-col gap-2">
    <!-- 附件标签列表 -->
    <div v-if="attachments.length > 0" class="flex flex-wrap items-center gap-2 px-1">
      <div
        v-for="item in attachments"
        :key="item.uid"
        class="flex items-center gap-1.5 max-w-[240px] h-10 px-2 bg-gray-100 rounded-lg text-gray-700"
        :title="
          item.truncated
            ? '附件内容过长，已截断'
            : item.note || item.name
        "
      >
        <!-- 图片附件展示缩略图 -->
        <img
          v-if="item.kind === 'image' && item.url"
          :src="item.url"
          class="flex-shrink-0 w-8 h-8 rounded object-cover"
          :alt="item.name"
        />
        <icon-file v-else class="flex-shrink-0" />
        <div class="flex-1 flex flex-col leading-4 overflow-hidden">
          <span class="text-xs truncate">{{ item.name }}</span>
          <span v-if="item.uploading" class="text-[11px] text-gray-400">
            {{ item.kind === 'image' ? '上传中...' : '解析中...' }}
          </span>
          <span v-else-if="item.kind !== 'text'" class="text-[11px] text-gray-400">
            {{ item.kind === 'image' ? '图片' : '文件' }}
          </span>
        </div>
        <a-spin v-if="item.uploading" :size="12" class="flex-shrink-0" />
        <icon-close
          v-else
          class="flex-shrink-0 cursor-pointer hover:text-red-600"
          @click="removeAttachment(item.uid)"
        />
      </div>
    </div>
    <!-- 输入框区域(聚焦时由容器呈现蓝色高亮，避免浏览器默认的黑色outline) -->
    <div
      :class="`flex items-end gap-1.5 px-2.5 py-1.5 border rounded-3xl bg-white transition-all focus-within:ring-4 ${
        recording
          ? 'border-red-300 bg-red-50/30 ring-red-100'
          : 'border-gray-200 hover:border-gray-300 focus-within:border-blue-400 focus-within:ring-blue-100'
      }`"
    >
      <!-- 文本输入框 -->
      <textarea
        ref="textareaRef"
        v-model="query"
        rows="1"
        :placeholder="recording ? '正在聆听，请说话...' : props.placeholder"
        class="flex-1 min-h-[44px] max-h-[160px] py-2.5 text-[15px] leading-6 resize-none bg-transparent text-gray-700 placeholder:text-gray-400 outline-none focus:outline-none focus-visible:outline-none"
        @input="autoResize"
        @keydown="handleKeydown"
      />
      <!-- 上传附件按钮(使用内联图标避免图标库差异) -->
      <a-tooltip content="上传文件/图片">
        <a-button
          type="text"
          shape="circle"
          class="flex-shrink-0 !text-gray-700 hover:!bg-gray-100"
          :disabled="loading"
          @click="pickFile"
        >
          <template #icon>
            <svg
              viewBox="0 0 24 24"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path d="M21 12.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6.5" />
              <line x1="17" y1="3" x2="17" y2="9" />
              <line x1="14" y1="6" x2="20" y2="6" />
            </svg>
          </template>
        </a-button>
      </a-tooltip>
      <!-- 语音输入按钮 -->
      <a-tooltip :content="recording ? '点击结束语音输入' : '语音输入'">
        <a-button
          type="text"
          shape="circle"
          class="flex-shrink-0"
          :class="recording ? '!text-red-600 !bg-red-50' : '!text-gray-700'"
          :disabled="loading"
          @click="toggleRecord"
        >
          <template #icon>
            <svg
              viewBox="0 0 24 24"
              width="18"
              height="18"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="9" y="2" width="6" height="12" rx="3" />
              <path d="M5 11a7 7 0 0 0 14 0" />
              <line x1="12" y1="18" x2="12" y2="22" />
            </svg>
          </template>
        </a-button>
      </a-tooltip>
      <input
        ref="fileInputRef"
        type="file"
        multiple
        class="hidden"
        :accept="props.accept || undefined"
        @change="handleFilesChange"
      />
      <!-- 发送按钮 -->
      <a-button
        type="text"
        shape="circle"
        class="flex-shrink-0 !text-gray-700"
        :loading="props.loading"
        :disabled="sendDisabled"
        @click="submit()"
      >
        <template #icon>
          <icon-send :size="18" />
        </template>
      </a-button>
    </div>
  </div>
</template>

<style scoped></style>
