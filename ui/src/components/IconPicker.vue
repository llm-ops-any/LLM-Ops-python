<script setup lang="ts">
import { useUploadImage } from '@/hooks/use-upload-file'

// 1.定义组件属性与事件
const props = defineProps({
  modelValue: { type: String, default: '' },
})
const emits = defineEmits(['update:modelValue', 'change'])

// 2.定义内置图标清单（SVG文件位于ui/public/app-icons，构建后通过/app-icons/静态访问）
const builtinIcons = [
  { name: '机器人', path: '/app-icons/robot.svg' },
  { name: '对话', path: '/app-icons/chat.svg' },
  { name: '文件夹', path: '/app-icons/folder.svg' },
  { name: '代码', path: '/app-icons/code.svg' },
  { name: '图表', path: '/app-icons/chart.svg' },
  { name: '闪电', path: '/app-icons/bolt.svg' },
  { name: '星星', path: '/app-icons/star.svg' },
  { name: '地球', path: '/app-icons/globe.svg' },
  { name: '音乐', path: '/app-icons/music.svg' },
  { name: '相机', path: '/app-icons/camera.svg' },
  { name: '火箭', path: '/app-icons/rocket.svg' },
  { name: '盾牌', path: '/app-icons/shield.svg' },
  { name: '设置', path: '/app-icons/gear.svg' },
  { name: '云端', path: '/app-icons/cloud.svg' },
  { name: '心形', path: '/app-icons/heart.svg' },
  { name: '植物', path: '/app-icons/leaf.svg' },
  { name: '购物', path: '/app-icons/bag.svg' },
  { name: '皇冠', path: '/app-icons/crown.svg' },
  { name: '咖啡', path: '/app-icons/coffee.svg' },
  { name: '指南针', path: '/app-icons/compass.svg' },
  { name: '实验', path: '/app-icons/flask.svg' },
  { name: '灵感', path: '/app-icons/bulb.svg' },
  { name: '时间', path: '/app-icons/clock.svg' },
  { name: '写作', path: '/app-icons/pencil.svg' },
]

// 3.定义图标选中函数（内置图标与被上传的自定义图标共用）
const selectIcon = (path: string) => {
  emits('update:modelValue', path)
  emits('change', path)
}

// 4.定义自定义图标上传处理器
const { image_url, handleUploadImage } = useUploadImage()
const handleCustomRequest = (option: any) => {
  // 4.1 从option中提取数据
  const { fileItem, onSuccess, onError } = option

  // 4.2 使用普通异步函数完成上传，上传完成后将COS地址回填至表单
  const uploadTask = async () => {
    try {
      await handleUploadImage(fileItem.file as File)
      selectIcon(image_url.value)
      onSuccess(image_url.value)
    } catch (error) {
      onError(error)
    }
  }
  uploadTask()

  return { abort: () => {} }
}
</script>

<template>
  <div class="w-full">
    <!-- 当前图标预览 + 自定义上传 -->
    <div class="flex items-center gap-3">
      <div
        class="w-14 h-14 shrink-0 rounded-xl border border-gray-200 bg-gray-50 overflow-hidden flex items-center justify-center"
      >
        <img v-if="props.modelValue" :src="props.modelValue" class="w-full h-full object-cover" />
        <icon-image v-else :size="20" class="text-gray-300" />
      </div>
      <div class="flex flex-col gap-1">
        <a-upload
          :show-file-list="false"
          accept="image/png, image/jpeg"
          :custom-request="handleCustomRequest"
        >
          <a-button class="rounded-lg">
            <template #icon>
              <icon-upload />
            </template>
            上传自定义图标
          </a-button>
        </a-upload>
        <div class="text-xs text-gray-500">或从下方选择一个内置图标</div>
      </div>
    </div>
    <!-- 内置图标网格 -->
    <div class="mt-3 grid grid-cols-10 gap-1.5">
      <div
        v-for="item in builtinIcons"
        :key="item.path"
        :title="item.name"
        class="cursor-pointer rounded-lg border-2 p-0.5 transition-all"
        :class="
          props.modelValue === item.path
            ? 'border-blue-500 bg-blue-50'
            : 'border-transparent hover:bg-gray-100'
        "
        @click="selectIcon(item.path)"
      >
        <img :src="item.path" :alt="item.name" class="block w-8 h-8 rounded-md" />
      </div>
    </div>
  </div>
</template>

<style scoped></style>
