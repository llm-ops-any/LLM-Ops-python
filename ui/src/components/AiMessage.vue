<script setup lang="ts">
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
  type PropType,
} from 'vue'
import MarkdownIt from 'markdown-it'
import DotFlashing from '@/components/DotFlashing.vue'
import AgentThought from './AgentThought.vue'
import 'github-markdown-css'

// 1.定义自定义组件所需数据
const props = defineProps({
  app: {
    type: Object,
    default: () => {
      return {}
    },
    required: true,
  },
  answer: { type: String, default: '', required: true },
  loading: { type: Boolean, default: false, required: false },
  latency: { type: Number, default: 0, required: false },
  total_token_count: { type: Number, default: 0, required: false },
  agent_thoughts: {
    type: Array as PropType<Record<string, any>[]>,
    default: () => [],
    required: true,
  },
  suggested_questions: { type: Array as PropType<string[]>, default: () => [], required: false },
  message_class: { type: String, default: '!bg-gray-100', required: false },
})
const emits = defineEmits(['selectSuggestedQuestion'])
// linkify: 裸 URL 自动转链接；breaks: 单个换行也换行
const md = MarkdownIt({ html: false, linkify: true, breaks: true })

// 链接：新窗口打开；商品详情链接渲染为「立即购买」按钮
const defaultLinkOpen = md.renderer.rules.link_open ?? ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const href = token.attrGet('href') || ''
  if (/^https?:\/\//.test(href)) {
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
  }
  if (/^https?:\/\/(detail\.tmall\.com|item\.taobao\.com|detail\.1688\.com|item\.jd\.com)\//.test(href)) {
    token.attrJoin('class', 'buy-btn')
  }
  return defaultLinkOpen(tokens, idx, options, env, self)
}

// 图片：懒加载 + 不带 referrer（规避图床防盗链）
md.renderer.rules.image = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  token.attrSet('alt', self.renderInlineAsText(token.children ?? [], options, env))
  token.attrSet('loading', 'lazy')
  token.attrSet('referrerpolicy', 'no-referrer')
  return self.renderToken(tokens, idx, options)
}

const compiledMarkdown = computed(() => {
  return md.render(props.answer)
})

// 2.横向溢出检测 + 展开全部
const messageRef = ref<HTMLElement | null>(null)
// 是否处于「展开全部」状态（表格/代码块按原始宽度展示，由气泡横向滚动）
const expanded = ref(false)
// 是否出现横向溢出，只有溢出时才展示切换按钮
const canToggle = ref(false)

const checkOverflow = (el: HTMLElement) => {
  // 气泡自身溢出
  if (el.scrollWidth > el.clientWidth + 1) return true
  // 表格 / 代码块内部滚动，也算溢出（默认态它们各自带滚动条）
  return Array.from(el.querySelectorAll<HTMLElement>('table, pre')).some(
    (node) => node.scrollWidth > node.clientWidth + 1,
  )
}

const measureOverflow = () => {
  const el = messageRef.value
  if (!el) {
    canToggle.value = false
    return
  }
  // 展开态下保持按钮可见，否则无法收起
  canToggle.value = expanded.value ? true : checkOverflow(el)
}

let resizeObserver: ResizeObserver | null = null
let mutationObserver: MutationObserver | null = null

const observeMessage = () => {
  resizeObserver?.disconnect()
  mutationObserver?.disconnect()
  const el = messageRef.value
  if (!el) return
  if (typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => measureOverflow())
    resizeObserver.observe(el)
  }
  if (typeof MutationObserver !== 'undefined') {
    // 流式输出时 v-html 内容会持续变化，内容变了重新测量
    mutationObserver = new MutationObserver(() => nextTick(measureOverflow))
    mutationObserver.observe(el, { childList: true, subtree: true, characterData: true })
  }
}

watch(
  () => props.loading,
  () => nextTick(() => {
    observeMessage()
    measureOverflow()
  }),
)

watch(
  () => props.answer,
  () => nextTick(measureOverflow),
)

onMounted(() => {
  observeMessage()
  measureOverflow()
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  mutationObserver?.disconnect()
})

const toggleExpand = () => {
  expanded.value = !expanded.value
  nextTick(measureOverflow)
}
</script>

<template>
  <div class="flex gap-2">
    <!-- 左侧图标 -->
    <a-avatar
      v-if="props.app?.icon"
      :size="30"
      shape="circle"
      class="flex-shrink-0"
      :image-url="props.app?.icon"
    />
    <a-avatar v-else :size="30" shape="circle" class="flex-shrink-0 bg-blue-700">
      <icon-apps />
    </a-avatar>
    <!-- 右侧名称与消息 -->
    <div class="flex-1 flex flex-col items-start gap-2">
      <!-- 应用名称 -->
      <div class="text-gray-700 font-bold">{{ props.app?.name }}</div>
      <!-- 推理步骤 -->
      <agent-thought :agent_thoughts="props.agent_thoughts" :loading="props.loading" />
      <!-- AI消息 -->
      <div
        v-if="props.loading && props.answer.trim() === ''"
        :class="`${props.message_class} border border-gray-200 text-gray-700 px-4 py-3 rounded-2xl break-all`"
      >
        <dot-flashing />
      </div>
      <div
        v-else
        ref="messageRef"
        :class="[
          props.message_class,
          'markdown-body ai-message-scroll border border-gray-200 text-gray-700 px-4 py-3 rounded-2xl overflow-x-auto',
          expanded ? 'ai-message-expanded' : 'break-all',
        ]"
        v-html="compiledMarkdown"
      ></div>
      <!-- 消息展示与操作 -->
      <div class="flex items-center justify-between">
        <!-- 消息数据额外展示 -->
        <a-space class="text-xs">
          <template #split>
            <a-divider direction="vertical" class="m-0" />
          </template>
          <div class="flex items-center gap-1 text-gray-500">
            <icon-check />
            {{ props.latency.toFixed(2) }}s
          </div>
          <div class="text-gray-500">{{ props.total_token_count }} Tokens</div>
          <a-button
            v-if="canToggle"
            type="text"
            size="mini"
            class="ai-message-toggle !text-gray-500 !px-0"
            @click="toggleExpand"
          >
            {{ expanded ? '收起' : '展开全部' }}
          </a-button>
        </a-space>
        <!-- 操作 -->
      </div>
      <!-- 建议问题列表 -->
      <div v-if="props.suggested_questions.length > 0" class="flex flex-col gap-2">
        <div
          v-for="(suggested_question, idx) in props.suggested_questions"
          :key="idx"
          class="px-4 py-1.5 border rounded-lg text-gray-700 cursor-pointer bg-white hover:bg-gray-50"
          @click="() => emits('selectSuggestedQuestion', suggested_question)"
        >
          {{ suggested_question }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 横向滚动：细滚动条，不占额外留白 */
.ai-message-scroll {
  scrollbar-width: thin;
  overflow-y: hidden;
}

.ai-message-scroll::-webkit-scrollbar {
  height: 6px;
}

.ai-message-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.ai-message-scroll::-webkit-scrollbar-thumb {
  background-color: rgba(0, 0, 0, 0.18);
  border-radius: 3px;
}

.ai-message-scroll::-webkit-scrollbar-thumb:hover {
  background-color: rgba(0, 0, 0, 0.32);
}

.ai-message-toggle {
  font-size: 12px !important;
  line-height: 1 !important;
}

/* 展开态：表格 / 代码块按内容原始宽度撑开，交给气泡横向滚动 */
.ai-message-expanded :deep(table) {
  display: table;
  width: max-content;
  max-width: none;
  overflow: visible;
}

.ai-message-expanded :deep(pre) {
  width: max-content;
  min-width: 100%;
  max-width: none;
  overflow: visible;
}
</style>
