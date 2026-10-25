<script setup lang="ts">
import { computed, ref } from 'vue'
import { Message } from '@arco-design/web-vue'

const props = defineProps<{
  /** 累加后的最终回答 */
  answer: string
  /** 推理链路（已过滤掉逐 token 的 agent_message） */
  thoughts: any[]
  /** 原始 SSE 文本 */
  rawStream: string
  /** 等价 curl（默认遮蔽凭证） */
  curl: string
  /** 等价 curl（含完整凭证，用于复制到终端复跑） */
  curlFull: string
  /** 错误信息原文 */
  error: string
  /** 是否正在请求中 */
  loading: boolean
}>()

const emits = defineEmits<{
  (e: 'clear-raw'): void
}>()

const activeTab = ref('answer')
const revealCredential = ref(false)
const showThoughts = ref(true)

// 展示用的 curl：默认遮蔽，用户可显式展开
const displayCurl = computed(() => (revealCredential.value ? props.curlFull : props.curl))

const copyText = async (text: string, tip: string) => {
  if (text === '') {
    Message.warning('当前没有可复制的内容')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    Message.success(tip)
  } catch {
    Message.error('当前浏览器不支持自动复制，请手动选中文本复制')
  }
}

// 复制 curl 时给的是含完整 Key 的版本，否则无法拿去终端复跑
const handleCopyCurl = () => copyText(props.curlFull, '已复制（含完整 API Key，请勿外传）')
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <a-tabs v-model:active-key="activeTab" type="text" class="playground-tabs">
      <!-- 一、回答 -->
      <a-tab-pane key="answer" title="回答">
        <div class="flex h-full min-h-0 flex-col gap-3 overflow-auto pr-1">
          <!-- 错误原文：一律原样展示，不能只弹 toast -->
          <div
            v-if="error"
            class="shrink-0 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          >
            <div class="mb-1 font-medium">请求失败（以下为服务端返回原文）</div>
            <div class="whitespace-pre-wrap break-all font-mono text-xs">{{ error }}</div>
          </div>

          <!-- 回答内容 -->
          <div class="min-h-[80px] shrink-0 whitespace-pre-wrap break-words text-sm text-gray-800">
            <span v-if="answer">{{ answer }}</span>
            <span v-else-if="loading" class="text-gray-400">正在等待模型输出…</span>
            <span v-else class="text-gray-400">尚未发起请求</span>
          </div>

          <!-- 推理链路 -->
          <div v-if="thoughts.length > 0" class="flex shrink-0 flex-col gap-2">
            <a-button
              type="text"
              size="mini"
              class="!w-fit !px-0 !text-gray-600"
              @click="showThoughts = !showThoughts"
            >
              <template #icon>
                <icon-down v-if="showThoughts" />
                <icon-right v-else />
              </template>
              推理链路（{{ thoughts.length }} 步）
            </a-button>
            <div v-if="showThoughts" class="flex flex-col gap-2">
              <div
                v-for="(thought, idx) in thoughts"
                :key="thought.id || idx"
                class="rounded-lg border border-gray-200 p-3"
              >
                <div class="mb-2 flex items-center gap-2">
                  <a-tag size="small" color="arcoblue">{{ thought.event }}</a-tag>
                  <span v-if="thought.tool" class="text-xs text-gray-500">
                    工具：{{ thought.tool }}
                  </span>
                  <span v-if="thought.latency" class="text-xs text-gray-400">
                    耗时 {{ Number(thought.latency).toFixed(2) }}s
                  </span>
                </div>
                <div v-if="thought.thought" class="mb-1 text-xs text-gray-700">
                  <span class="text-gray-400">思考：</span>
                  <span class="whitespace-pre-wrap break-all">{{ thought.thought }}</span>
                </div>
                <div v-if="thought.tool_input && Object.keys(thought.tool_input).length > 0" class="mb-1">
                  <div class="text-xs text-gray-400">入参：</div>
                  <pre class="max-h-40 overflow-auto rounded bg-gray-50 p-2 font-mono text-xs text-gray-700">{{ JSON.stringify(thought.tool_input, null, 2) }}</pre>
                </div>
                <div v-if="thought.observation" class="text-xs text-gray-700">
                  <span class="text-gray-400">观测：</span>
                  <span class="whitespace-pre-wrap break-all">{{ thought.observation }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </a-tab-pane>

      <!-- 二、原始事件流 -->
      <a-tab-pane key="raw" title="原始事件流">
        <div class="flex h-full flex-col gap-2 overflow-hidden">
          <div class="flex items-center justify-between">
            <span class="text-xs text-gray-500">
              服务端逐帧返回的原始文本（含空行分隔与 ping 心跳），排障时以这里为准
            </span>
            <div class="flex items-center gap-2">
              <a-button type="text" size="mini" @click="copyText(rawStream, '已复制事件流原文')">
                复制
              </a-button>
              <a-button type="text" size="mini" @click="emits('clear-raw')">清空</a-button>
            </div>
          </div>
          <pre
            class="flex-1 overflow-auto rounded-lg bg-gray-900 p-3 font-mono text-xs leading-5 text-gray-100"
          >{{ rawStream || '（暂无输出）' }}</pre>
        </div>
      </a-tab-pane>

      <!-- 三、等价请求 -->
      <a-tab-pane key="curl" title="等价请求">
        <div class="flex h-full flex-col gap-2 overflow-hidden">
          <div class="flex items-center justify-between">
            <span class="text-xs text-gray-500">
              由端点元数据 + 当前表单值生成，可原样粘贴到终端执行
            </span>
            <div class="flex items-center gap-2">
              <a-checkbox v-model="revealCredential" class="!text-xs">
                显示完整 Key
              </a-checkbox>
              <a-button type="text" size="mini" @click="handleCopyCurl">
                复制（含完整 Key）
              </a-button>
            </div>
          </div>
          <pre
            class="flex-1 overflow-auto rounded-lg bg-gray-900 p-3 font-mono text-xs leading-5 text-gray-100"
          >{{ displayCurl }}</pre>
          <div class="text-xs text-gray-400">
            提示：复制到终端会带上完整 API Key，请勿外传；同一台机器不走浏览器，因此不受跨域限制
          </div>
        </div>
      </a-tab-pane>
    </a-tabs>
  </div>
</template>

<style scoped>
/*
 * Arco Tabs 默认给内容区的是「高度随内容」：.arco-tabs-content{padding-top:16px;overflow:hidden}
 * .arco-tabs-content-item{height:0;overflow:hidden} / -active{height:auto}
 * 结果：面板里的 h-full / overflow-auto 拿不到确定高度，内容超出后被裁掉且无法滚动。
 * 这里把 tabs 改成纵向 flex，并把内容区高度改成确定值，滚动交回面板自己。
 */
.playground-tabs {
  display: flex;
  flex: 1 1 0%;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.playground-tabs :deep(.arco-tabs-content) {
  display: flex;
  flex: 1 1 0%;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.playground-tabs :deep(.arco-tabs-content-list) {
  flex: 1 1 0%;
  min-height: 0;
}

.playground-tabs :deep(.arco-tabs-content-item.arco-tabs-content-item-active) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}

/* pane 是插槽的真正容器，它不给定高度时里面的 h-full 依然是 auto */
.playground-tabs :deep(.arco-tabs-pane) {
  height: 100%;
  min-height: 0;
  overflow: hidden;
}
</style>
