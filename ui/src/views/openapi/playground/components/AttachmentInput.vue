<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { uploadFileText } from '@/services/upload-file'
import type { ChatAttachment } from '@/models/upload-file'

// ============================================================================
// 附件选择器（Playground 用户提问下方）
// - 只负责「选文件 → 上传解析 → 交出 ChatAttachment[]」，不关心端点与请求体
// - 上传走登录态接口 /api/upload-files/attachment，与聊天请求的 API Key 鉴权互不影响
// - 上限由父级通过 limit 传入（与后端 upload_file_entity.py 同一组数字）
// ============================================================================

const props = defineProps<{
  /** 已上传成功的附件列表 */
  modelValue: ChatAttachment[]
  /** 数量与单文件体积上限 */
  limit: { count: number; size: number }
  /** 请求进行中时禁止增删 */
  disabled?: boolean
}>()

const emits = defineEmits<{
  (e: 'update:modelValue', files: ChatAttachment[]): void
}>()

const inputRef = ref<HTMLInputElement | null>(null)

// 上传中的文件：此时还没有 ChatAttachment，先占位展示，避免用户以为没反应
const uploading = ref<{ uid: number; name: string; size: number }[]>([])
let uid = 0

// 组件内的权威副本：连续上传时父级 props 要到下一次渲染才回流，
// 若直接以 props.modelValue 累加，同一个 tick 内多次 emit 会互相覆盖导致丢附件
const files = ref<ChatAttachment[]>([])
watch(
  () => props.modelValue,
  (value) => {
    files.value = Array.isArray(value) ? [...value] : []
  },
  { immediate: true },
)

// 已选 + 上传中，用于判断是否还有剩余名额
const totalCount = computed(() => files.value.length + uploading.value.length)

// 统一入口：先更新本地副本再通知父级，保证「本地即时、父级最终一致」
const commit = (next: ChatAttachment[]) => {
  files.value = next
  emits('update:modelValue', next)
}

const sizeText = (size: number) => {
  if (!size || size < 0) return '0 KB'
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

// kind 由服务端判定：text=解析出正文、image=图片、file=其它二进制
const kindLabel = (kind?: string) => {
  if (kind === 'image') return '图片'
  if (kind === 'file') return '文件'
  return '文档'
}

const sizeLimitText = computed(() => `${Math.round(props.limit.size / 1024 / 1024)}MB`)

const pickFile = () => {
  if (props.disabled) return
  inputRef.value?.click()
}

const handleFileChange = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const selected = Array.from(input.files ?? [])
  // 立即清空，保证再次选同一个文件也能触发 change
  input.value = ''
  if (selected.length === 0) return

  // 1.数量上限：只处理剩余名额内的文件
  const remain = props.limit.count - totalCount.value
  if (remain <= 0) {
    Message.warning(`单次最多携带 ${props.limit.count} 个附件，请先删除已选附件`)
    return
  }
  if (selected.length > remain) {
    Message.warning(
      `单次最多携带 ${props.limit.count} 个附件，已忽略多出的 ${selected.length - remain} 个`,
    )
  }

  // 2.逐个串行上传：附件解析吃 CPU，并发上传会把后端打满
  for (const file of selected.slice(0, remain)) {
    if (file.size > props.limit.size) {
      Message.error(`「${file.name}」超过 ${sizeLimitText.value}，已跳过`)
      continue
    }

    const current = { uid: ++uid, name: file.name, size: file.size }
    uploading.value.push(current)
    try {
      const result = await uploadFileText(file)
      const attachment = result?.data
      if (!attachment) throw new Error('服务端未返回附件信息')
      // 以本地副本为准追加，避免连续上传时 props 未回流导致的覆盖丢件
      commit([...files.value, attachment])
    } catch (error: any) {
      // 失败原因原样透出（登录过期 / 体积超限 / 解析失败），不能只弹一个通用错误
      Message.error(`「${file.name}」上传失败：${error?.message ?? error}`)
    } finally {
      uploading.value = uploading.value.filter((item) => item.uid !== current.uid)
    }
  }
}

const removeAt = (index: number) => {
  if (props.disabled) return
  const next = files.value.slice()
  next.splice(index, 1)
  commit(next)
}
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex flex-wrap items-center gap-2">
      <!-- 已上传成功的附件 -->
      <a-tag
        v-for="(file, index) in files"
        :key="`${file.name}-${index}`"
        class="attachment-chip"
        :closable="!disabled"
        data-testid="attachment-chip"
        @close="removeAt(index)"
      >
        <span class="mr-1 text-gray-400">[{{ kindLabel(file.kind) }}]</span>
        <span class="max-w-[160px] truncate align-bottom">{{ file.name }}</span>
        <span class="ml-1 text-gray-400">{{ sizeText(file.size) }}</span>
      </a-tag>

      <!-- 上传中的占位 -->
      <a-tag
        v-for="item in uploading"
        :key="item.uid"
        class="attachment-chip !text-gray-500"
        data-testid="attachment-uploading"
      >
        <icon-loading class="mr-1" />
        <span class="max-w-[160px] truncate align-bottom">{{ item.name }}</span>
        <span class="ml-1">{{ sizeText(item.size) }}</span>
      </a-tag>

      <a-button
        size="small"
        :disabled="disabled || totalCount >= limit.count"
        data-testid="attachment-add"
        @click="pickFile"
      >
        <template #icon>
          <icon-plus />
        </template>
        添加附件
      </a-button>
    </div>

    <!-- 隐藏的原生选择器：项目未引入上传组件的自定义请求模式，这里自己控制流程 -->
    <input ref="inputRef" type="file" multiple class="hidden" @change="handleFileChange" />

    <div v-if="totalCount > 0" class="text-xs text-gray-400">
      已选 {{ totalCount }} / {{ limit.count }}；附件只参与本次请求，不会写进对话历史
    </div>
  </div>
</template>

<style scoped>
.attachment-chip {
  max-width: 100%;
  padding: 2px 8px;
  border-radius: 6px;
  line-height: 20px;
}
</style>
