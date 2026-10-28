<script setup lang="ts">
import { type PropType } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app'

// CR-16102803 / FR-06：应用编排的「语音转文本」开关
// 说明：开关只落 app_config_version.speech_to_text（字段与校验既有，无需迁移，D-09）；
//      具体走哪个引擎由「设置 → 语音服务」决定，不在应用级重复配置。
const props = defineProps({
  app_id: { type: String, default: '', required: true },
  speech_to_text: {
    type: Object as PropType<{ enable: boolean }>,
    default: () => {
      return { enable: false }
    },
    required: true,
  },
})
const emits = defineEmits(['update:speech_to_text'])
const { handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()
</script>

<template>
  <div class="">
    <a-collapse-item key="speech_to_text" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">语音转文本</div>
      </template>
      <template #extra>
        <a-dropdown
          @select="
            async (value) => {
              if (Boolean(value) !== props.speech_to_text?.enable) {
                emits('update:speech_to_text', { enable: Boolean(value) })
                await handleUpdateDraftAppConfig(props.app_id, {
                  speech_to_text: { enable: Boolean(value) },
                })
              }
            }
          "
        >
          <a-button
            size="mini"
            class="rounded-lg flex items-center gap-1 px-1"
            data-testid="ability-speech-to-text-toggle"
            @click.stop
          >
            {{ props.speech_to_text.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-red-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <div class="text-xs text-gray-500 leading-[22px]">
        支持在对话框录入语音并转成文字。默认使用浏览器识别（免费、无需配置）；在「设置 → 语音服务」切到专用语音引擎后改为服务端识别。
      </div>
    </a-collapse-item>
  </div>
</template>

<style scoped></style>
