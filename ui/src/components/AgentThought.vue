<script setup lang="ts">
import { computed, onMounted, ref, watch, type PropType } from 'vue'
import { QueueEvent } from '@/config'
import { useToolMeta } from '@/hooks/use-tool-meta'

// 1.定义自定义组件所需数据
const props = defineProps({
  loading: { type: Boolean, default: false, required: true },
  agent_thoughts: {
    type: Array as PropType<Record<string, any>[]>,
    default: () => [],
    required: true,
  },
})
const visible = ref(false)

// 2.需要展示在运行流程中的事件类型
const visibleEvents = [
  QueueEvent.longTermMemoryRecall,
  QueueEvent.agentThought,
  QueueEvent.datasetRetrieval,
  QueueEvent.agentAction,
  QueueEvent.agentMessage,
]

// 3.过滤出需要展示的运行步骤，并按position(步骤序号)升序排列
//   说明：历史消息的agent_thoughts来自数据库，若未带position则保持原顺序(position默认0，排序稳定)
const thoughtList = computed(() =>
  props.agent_thoughts
    .filter((item: any) => visibleEvents.includes(item.event))
    .slice()
    .sort((a: any, b: any) => (a.position ?? 0) - (b.position ?? 0)),
)

// 4.步骤默认全部收起，只展示流程名称+耗时，详细内容由用户手动点开
//   watch仅用于清理已不存在的步骤，避免残留展开态
const activeKeys = ref<string[]>([])
watch(
  () => thoughtList.value.map((item: any) => item.id),
  (ids: string[]) => {
    activeKeys.value = activeKeys.value.filter((id) => ids.includes(id))
  },
  { immediate: true },
)

// 5.事件标题字典
const titles: Record<string, string> = {
  [QueueEvent.longTermMemoryRecall]: '长期记忆召回',
  [QueueEvent.agentThought]: '智能体推理',
  [QueueEvent.datasetRetrieval]: '搜索知识库',
  [QueueEvent.agentAction]: '调用工具',
  [QueueEvent.agentMessage]: '智能体消息',
}

// 6.工具元信息：把工具标识映射成工作流名称/内置工具中文名
const { toolMeta, loadToolMeta } = useToolMeta()
onMounted(() => loadToolMeta())

// 6.1 标题：区分「调用工作流 / 调用内置工具 / 调用工具」，并展示可读名称
const eventTitle = (agent_thought: any) => {
  const base = titles[agent_thought.event] || agent_thought.event || '未知步骤'
  const tool = agent_thought.tool
  if (!tool) return base

  // 仅工具调用需要附加工具信息，知识库检索固定展示即可
  if (agent_thought.event !== QueueEvent.agentAction) return base

  const meta = toolMeta.value[tool]
  if (meta?.type === 'workflow') return `调用工作流 · ${meta.label}`
  if (meta?.type === 'builtin') return `调用内置工具 · ${meta.label}`
  return `${base} · ${tool}`
}

// 7.工具调用参数：agent_thought的thought是tool_calls的JSON字符串，解析成可读形式
const formatThought = (raw: string) => {
  if (!raw) return '-'
  try {
    const calls = JSON.parse(raw)
    if (Array.isArray(calls)) {
      return calls
        .map(
          (call: any) =>
            `${call.name || '工具'}(${
              typeof call.args === 'string' ? call.args : JSON.stringify(call.args ?? {})
            })`,
        )
        .join('\n')
    }
  } catch (e) {
    // 非tool_calls结构，直接展示原文
  }
  return raw
}

// 8.工具返回：observation是json.dumps的结果(可能双层转义)，优先取出output字段并反转义
const formatObservation = (raw: string) => {
  if (!raw) return '-'
  try {
    let value = JSON.parse(raw)
    if (typeof value === 'string') {
      try {
        value = JSON.parse(value)
      } catch (e) {
        return value
      }
    }
    if (value && typeof value === 'object') {
      if ('output' in value) return String((value as any).output)
      return JSON.stringify(value, null, 2)
    }
    return String(value)
  } catch (e) {
    return raw
  }
}

// 9.工具调用参数：tool_input为模型生成的入参对象/JSON字符串，展开后分行展示
const formatParams = (input: any) => {
  if (!input) return '-'
  let value = input
  if (typeof value === 'string') {
    try {
      value = JSON.parse(value)
    } catch (e) {
      return value
    }
  }
  if (value && typeof value === 'object') {
    return Object.entries(value)
      .map(([key, val]) => `${key}: ${typeof val === 'object' ? JSON.stringify(val) : val}`)
      .join('\n')
  }
  return String(value)
}

// 10.按事件类型计算展示内容
const contentOf = (agent_thought: any) => {
  if (agent_thought.event === QueueEvent.agentThought) return formatThought(agent_thought.thought)
  if (
    agent_thought.event === QueueEvent.agentAction ||
    agent_thought.event === QueueEvent.datasetRetrieval
  ) {
    return formatObservation(agent_thought.observation)
  }
  return agent_thought.thought || '-'
}
</script>

<template>
  <!-- 智能体推理步骤 -->
  <div :class="`flex flex-col rounded-2xl border ${visible ? 'w-[480px]' : 'w-[200px]'}`">
    <div
      :class="`flex items-center justify-between h-10 rounded-2xl bg-gray-100 px-4 text-gray-700 cursor-pointer w-auto ${visible ? 'rounded-bl-none rounded-br-none' : ''}`"
      @click="visible = !visible"
    >
      <!-- 左侧图标与标题 -->
      <div class="flex items-center gap-2">
        <icon-list />
        {{ visible ? '隐藏' : '显示' }}运行流程
        <span class="text-xs text-gray-400">{{ thoughtList.length }} 步</span>
      </div>
      <!-- 右侧图标 -->
      <div class="">
        <template v-if="props.loading">
          <icon-loading />
        </template>
        <template v-else>
          <icon-up v-if="visible" />
          <icon-down v-else />
        </template>
      </div>
    </div>
    <!-- 底部内容 -->
    <a-collapse
      class="agent-thought"
      v-if="visible"
      v-model:active-key="activeKeys"
      destroy-on-hide
      :bordered="false"
    >
      <a-collapse-item v-for="agent_thought in thoughtList" :key="agent_thought.id" :name="agent_thought.id">
        <template #expand-icon>
          <icon-file v-if="agent_thought.event === QueueEvent.longTermMemoryRecall" />
          <icon-language v-else-if="agent_thought.event === QueueEvent.agentThought" />
          <icon-storage v-else-if="agent_thought.event === QueueEvent.datasetRetrieval" />
          <icon-tool v-else-if="agent_thought.event === QueueEvent.agentAction" />
          <icon-message v-else-if="agent_thought.event === QueueEvent.agentMessage" />
        </template>
        <template #header>
          <div class="text-gray-700">{{ eventTitle(agent_thought) }}</div>
        </template>
        <template #extra>
          <div class="text-gray-500">{{ Number(agent_thought.latency || 0).toFixed(2) }}s</div>
        </template>
        <div class="flex flex-col gap-2 max-h-[320px] overflow-auto">
          <!-- 工具调用参数 -->
          <div
            v-if="agent_thought.event === QueueEvent.agentAction && agent_thought.tool_input"
            class="flex flex-col gap-1"
          >
            <div class="text-xs text-gray-400">调用参数</div>
            <div class="text-xs text-gray-600 whitespace-pre-wrap break-all">
              {{ formatParams(agent_thought.tool_input) }}
            </div>
          </div>
          <!-- 推理内容/工具返回 -->
          <div class="flex flex-col gap-1">
            <div v-if="agent_thought.event === QueueEvent.agentAction" class="text-xs text-gray-400">
              返回结果
            </div>
            <div class="text-xs text-gray-500 whitespace-pre-wrap break-all">
              {{ contentOf(agent_thought) }}
            </div>
          </div>
        </div>
      </a-collapse-item>
    </a-collapse>
  </div>
</template>

<style>
.agent-thought {
  .arco-collapse-item-content {
    padding: 0 16px;
  }
}
</style>
