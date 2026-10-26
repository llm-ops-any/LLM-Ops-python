<script setup lang="ts">
import type { PropType } from 'vue'
import type { ChatAttachment } from '@/models/upload-file'

// 1.定义自定义组件所需数据
const props = defineProps({
  account: {
    type: Object,
    default: () => {
      return {}
    },
    required: true,
  },
  query: { type: String, default: '', required: true },
  // 随本条消息上传的附件(服务端已持久化，历史消息与新消息都会传入)
  attachments: {
    type: Array as PropType<ChatAttachment[]>,
    default: () => [],
  },
})
</script>

<template>
  <div class="flex gap-2">
    <!-- 左侧头像 -->
    <a-avatar :size="30" shape="circle" class="flex-shrink-0" :image-url="props.account?.avatar" />
    <!-- 右侧昵称与消息 -->
    <div class="flex flex-col items-start gap-2">
      <!-- 账号昵称 -->
      <div class="text-gray-700 font-bold">{{ props.account?.name }}</div>
      <!-- 附件标签(图片展示缩略图，其它展示文件标签) -->
      <div v-if="props.attachments.length > 0" class="flex flex-wrap items-center gap-2">
        <a-image
          v-for="(attachment, idx) in props.attachments.filter(
            (item) => item.kind === 'image' && item.url,
          )"
          :key="`image-${idx}`"
          :src="attachment.url"
          :alt="attachment.name"
          width="72"
          class="rounded-lg overflow-hidden"
        />
        <div
          v-for="(attachment, idx) in props.attachments.filter(
            (item) => item.kind !== 'image' || !item.url,
          )"
          :key="`file-${idx}`"
          class="flex items-center gap-1.5 max-w-[220px] px-2.5 py-1 bg-blue-50 border border-blue-200 rounded-lg text-gray-700"
          :title="
            attachment.truncated
              ? '附件内容过长，已截断'
              : attachment.kind === 'file'
                ? '该附件未解析出文本，仅提供文件地址'
                : attachment.name
          "
        >
          <icon-file class="flex-shrink-0" />
          <span class="text-xs truncate">{{ attachment.name }}</span>
        </div>
      </div>
      <!-- 人类消息 -->
      <div class="bg-blue-100 border border-blue-200 text-gray-700 px-4 py-3 rounded-2xl break-all">
        {{ props.query }}
      </div>
    </div>
  </div>
</template>

<style scoped></style>
