<script setup lang="ts">
import { type PropType } from 'vue'
import { useUpdateDraftAppConfig } from '@/hooks/use-app'

// CR-16102803 / FR-06：应用编排的「文本转语音」开关
// 说明：音色与引擎在「设置 → 语音服务」统一配置，这里只管开不开（避免两处配置打架）。
const props = defineProps({
  app_id: { type: String, default: '', required: true },
  text_to_speech: {
    type: Object as PropType<{ enable: boolean; voice: string; auto_play: boolean }>,
    default: () => {
      return { enable: false, voice: 'echo', auto_play: false }
    },
    required: true,
  },
})
const emits = defineEmits(['update:text_to_speech'])
const { handleUpdateDraftAppConfig } = useUpdateDraftAppConfig()
</script>

<template>
  <div class="">
    <a-collapse-item key="text_to_speech" class="app-ability-item">
      <template #header>
        <div class="text-gray-700 font-bold">文本转语音</div>
      </template>
      <template #extra>
        <a-dropdown
          @select="
            async (value) => {
              if (Boolean(value) !== props.text_to_speech?.enable) {
                emits('update:text_to_speech', { ...props.text_to_speech, enable: Boolean(value) })
                await handleUpdateDraftAppConfig(props.app_id, {
                  text_to_speech: { ...props.text_to_speech, enable: Boolean(value) },
                })
              }
            }
          "
        >
          <a-button
            size="mini"
            class="rounded-lg flex items-center gap-1 px-1"
            data-testid="ability-text-to-speech-toggle"
            @click.stop
          >
            {{ props.text_to_speech.enable ? '开启' : '关闭' }}
            <icon-down />
          </a-button>
          <template #content>
            <a-doption :value="1" class="text-xs py-1.5 text-gray-700">开启</a-doption>
            <a-doption :value="0" class="text-xs py-1.5 text-red-700">关闭</a-doption>
          </template>
        </a-dropdown>
      </template>
      <div class="text-xs text-gray-500 leading-[22px]">
        在 AI 回复上显示播放按钮，可把回答念出来。浏览器引擎零成本直接朗读；切换到专用语音引擎后由服务端合成，
        引擎、模型与音色在「设置 → 语音服务」中配置。
      </div>
    </a-collapse-item>
  </div>
</template>

<style scoped></style>
