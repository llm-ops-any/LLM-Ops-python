<script setup lang="ts">
import { computed } from 'vue'
import type { EndpointField, OpenAPIEndpoint } from '../endpoints'

// 本组件不认识任何具体端点，一切渲染都由 endpoint 元数据驱动

const props = defineProps<{
  endpoint: OpenAPIEndpoint
  values: Record<string, any>
  errors: Record<string, string>
  options: { apps: any[]; apiKeys: any[] }
  session: { task_id: string; conversation_id: string; end_user_id: string }
  loading: boolean
  stopping: boolean
}>()

const emits = defineEmits<{
  (e: 'update:values', values: Record<string, any>): void
  (e: 'send'): void
  (e: 'stop'): void
  (e: 'clear-session'): void
}>()

// 1.按 showWhen 过滤出当前应展示的字段
const visibleFields = computed<EndpointField[]>(() =>
  props.endpoint.fields.filter((field) => {
    if (!field.showWhen) return true
    return props.values[field.showWhen.field] === field.showWhen.equals
  }),
)

// 2.取字段的动态选项
const optionsOf = (field: EndpointField) => {
  if (field.optionSource === 'apps') return props.options.apps
  if (field.optionSource === 'apiKeys') return props.options.apiKeys
  return []
}

// 3.更新单个字段（整体抛给父级，保持单向数据流）
const updateField = (name: string, value: unknown) => {
  emits('update:values', { ...props.values, [name]: value })
}

// 4.路径占位符对应的字段必须已填，否则发送按钮不可用
const pathReady = computed(() =>
  props.endpoint.fields
    .filter((field) => field.in === 'path')
    .every((field) => {
      const value = props.values[field.name]
      return value !== undefined && value !== null && value !== ''
    }),
)

// 5.是否处于「可停止」状态：流式进行中且已拿到 task_id
const canStop = computed(
  () => props.loading && props.endpoint.streamField !== undefined && props.session.task_id !== '',
)

// 6.是否有会话状态可清空
const hasSession = computed(
  () => props.session.task_id !== '' || props.session.conversation_id !== '',
)
</script>

<template>
  <div class="flex flex-col gap-5">
    <!-- 请求字段 -->
    <div v-for="field in visibleFields" :key="field.name" class="flex flex-col gap-1.5">
      <div class="flex items-center gap-1 text-sm font-medium text-gray-700">
        <span>{{ field.label }}</span>
        <span v-if="field.required" class="text-red-500">*</span>
        <span v-if="field.in === 'path'" class="text-xs font-normal text-gray-400">（路径参数）</span>
        <span v-else-if="field.in === 'header'" class="text-xs font-normal text-gray-400">（请求头）</span>
      </div>

      <!-- 布尔类型 -->
      <a-switch
        v-if="field.type === 'boolean'"
        :model-value="Boolean(values[field.name])"
        @change="(value: any) => updateField(field.name, value)"
      />

      <!-- 枚举类型：带动态选项；API Key 支持手动粘贴 -->
      <a-select
        v-else-if="field.type === 'enum'"
        :model-value="values[field.name]"
        :placeholder="field.placeholder"
        :error="Boolean(errors[field.name])"
        :allow-search="field.optionSource === 'apiKeys'"
        :allow-create="field.optionSource === 'apiKeys'"
        allow-clear
        @change="(value: any) => updateField(field.name, value)"
      >
        <a-option
          v-for="option in optionsOf(field)"
          :key="option.value"
          :value="option.value"
          :label="option.label"
        >
          {{ option.label }}
        </a-option>
      </a-select>

      <!-- 字符串类型 -->
      <a-input
        v-else
        :model-value="values[field.name]"
        :placeholder="field.placeholder"
        :error="Boolean(errors[field.name])"
        allow-clear
        @input="(value: string) => updateField(field.name, value)"
      />

      <div v-if="errors[field.name]" class="text-xs text-red-500">{{ errors[field.name] }}</div>
      <div v-else-if="field.tip" class="text-xs text-gray-500">{{ field.tip }}</div>
    </div>

    <!-- 会话状态：只读，由服务端回带，用于多轮对话与停止 -->
    <div class="flex flex-col gap-2 rounded-lg bg-gray-50 p-3">
      <div class="flex items-center justify-between">
        <span class="text-sm font-medium text-gray-700">会话状态</span>
        <a-button
          v-if="hasSession"
          type="text"
          size="mini"
          class="!text-gray-600"
          @click="emits('clear-session')"
        >
          清空会话
        </a-button>
      </div>
      <div class="flex items-center gap-2 text-xs">
        <span class="w-28 flex-shrink-0 text-gray-500">conversation_id</span>
        <span class="truncate text-gray-700">{{ session.conversation_id || '（首轮对话后回带）' }}</span>
      </div>
      <div class="flex items-center gap-2 text-xs">
        <span class="w-28 flex-shrink-0 text-gray-500">end_user_id</span>
        <span class="truncate text-gray-700">{{ session.end_user_id || '（首轮对话后回带）' }}</span>
      </div>
      <div class="flex items-center gap-2 text-xs">
        <span class="w-28 flex-shrink-0 text-gray-500">task_id</span>
        <span class="truncate text-gray-700">{{ session.task_id || '（流式对话开始后回带）' }}</span>
      </div>
      <div class="text-xs text-gray-400">
        以上三项由服务端回带并自动用于后续请求，不需要也不建议手动填写
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="flex items-center gap-3">
      <a-button
        type="primary"
        class="rounded-lg"
        :loading="loading"
        :disabled="!pathReady || loading"
        @click="emits('send')"
      >
        发送请求
      </a-button>
      <a-button
        v-if="canStop"
        class="rounded-lg"
        :loading="stopping"
        @click="emits('stop')"
      >
        <template #icon>
          <icon-poweroff />
        </template>
        停止响应
      </a-button>
      <span v-if="!pathReady" class="text-xs text-gray-500">
        请先填写路径参数（如 task_id）
      </span>
    </div>
  </div>
</template>

<style scoped></style>
