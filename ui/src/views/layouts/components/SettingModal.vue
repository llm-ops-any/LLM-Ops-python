<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAccountStore } from '@/stores/account'
import {
  useGetCurrentUser,
  useUpdateAvatar,
  useUpdateName,
  useUpdatePassword,
} from '@/hooks/use-account'
import { useUploadImage } from '@/hooks/use-upload-file'
import {
  useGetModelProvider,
  useTestModelProviderConnection,
  useUpdateModelProvider,
} from '@/hooks/use-model-provider'
import { useSpeechProvider } from '@/hooks/use-audio'
import type { SpeechEngine } from '@/models/audio'

// 1.定义自定义组件所需数据
const props = defineProps({
  visible: { type: Boolean, required: true },
})
const emits = defineEmits(['update:visible'])
const updateName = ref(false)
const updatePassword = ref(false)
const accountStore = useAccountStore()
const { current_user, loadCurrentUser } = useGetCurrentUser()
const { handleUpdateAvatar } = useUpdateAvatar()
const { handleUpdateName } = useUpdateName()
const { handleUpdatePassword } = useUpdatePassword()
const { image_url, handleUploadImage } = useUploadImage()
const accountForm = ref({
  fileList: [{ uid: '1', name: '账号头像', url: accountStore.account.avatar }],
  name: accountStore.account.name,
  avatar: accountStore.account.avatar,
  password: '',
  email: accountStore.account.email,
})

// 2.更新当前账号信息
const updateAccount = async () => {
  await loadCurrentUser()
  accountStore.update(current_user.value)
}

// 3.大模型设置相关数据与处理器
const activeMenu = ref<'account' | 'model_provider' | 'speech_provider'>('account')
const modelForm = ref({ base_url: '', api_key: '' })
const updateApiKey = ref(false)
const { setting: modelSetting, loadSetting } = useGetModelProvider()
const { handleUpdateSetting } = useUpdateModelProvider()
const { handleTestConnection } = useTestModelProviderConnection()

// 加载大模型设置，密钥输入框始终为空且不进入修改态
const loadModelProviderSetting = async () => {
  await loadSetting()
  modelForm.value.base_url = modelSetting.value.base_url
  modelForm.value.api_key = ''
  updateApiKey.value = false
}

// 保存大模型设置，密钥留空表示不修改已保存的密钥
const handleSaveModelProvider = async () => {
  const apiKey = updateApiKey.value ? modelForm.value.api_key.trim() : ''
  const data = await handleUpdateSetting(modelForm.value.base_url.trim(), apiKey)
  modelSetting.value = data
  modelForm.value.api_key = ''
  updateApiKey.value = false
}

// 测试大模型服务连通性，使用当前输入值，未填写则使用已保存配置
const handleTestModelProvider = async () => {
  const apiKey = updateApiKey.value ? modelForm.value.api_key.trim() : ''
  await handleTestConnection(modelForm.value.base_url.trim(), apiKey)
}

// 4.语音服务设置相关数据与处理器（CR-16102803 / FR-01）
const {
  setting: speechSetting,
  loadSpeechSetting,
  saveSpeechSetting,
  testSpeechSetting,
} = useSpeechProvider()
const updateSpeechKey = ref(false)
const speechForm = ref({
  engine: 'browser' as SpeechEngine,
  dashscope_api_key: '',
  omni_model: '',
  omni_voice: '',
  omni_host: '',
  cosyvoice_model: '',
  cosyvoice_voice: '',
  paraformer_model: '',
})

// 加载语音服务设置，密钥输入框始终为空
const loadSpeechProviderSetting = async () => {
  const data = await loadSpeechSetting(true)
  speechForm.value = {
    engine: data.engine,
    dashscope_api_key: '',
    omni_model: data.omni_model,
    omni_voice: data.omni_voice,
    omni_host: data.omni_host,
    cosyvoice_model: data.cosyvoice_model,
    cosyvoice_voice: data.cosyvoice_voice,
    paraformer_model: data.paraformer_model,
  }
  updateSpeechKey.value = false
}

// 保存语音服务设置，密钥留空表示不修改已保存的密钥
const handleSaveSpeechProvider = async () => {
  const apiKey = updateSpeechKey.value ? speechForm.value.dashscope_api_key.trim() : ''
  const data = await saveSpeechSetting({
    engine: speechForm.value.engine,
    dashscope_api_key: apiKey,
    omni_model: speechForm.value.omni_model,
    omni_voice: speechForm.value.omni_voice,
    omni_host: speechForm.value.omni_host,
    cosyvoice_model: speechForm.value.cosyvoice_model,
    cosyvoice_voice: speechForm.value.cosyvoice_voice,
    paraformer_model: speechForm.value.paraformer_model,
  })
  speechSetting.value = data
  speechForm.value.dashscope_api_key = ''
  updateSpeechKey.value = false
}

// 测试当前引擎能否真的出声
const handleTestSpeechProvider = async () => {
  await testSpeechSetting()
}

// 5.关闭模态窗处理器
const handleCancel = () => emits('update:visible', false)

// 5.监听模态窗关闭事件
watch(
  () => props.visible,
  (newValue) => {
    if (!newValue) {
      // 如果为关闭模态窗则重置表单，并关闭所有输入框
      updatePassword.value = false
      updateName.value = false
      updateApiKey.value = false
      modelForm.value.api_key = ''
    } else {
      // 打开模态窗时拉取最新的大模型设置，保证展示的是当前生效配置
      loadModelProviderSetting()
      loadSpeechProviderSetting()
    }

    // 无论是开启还是关闭模态窗，均赋初始值，可以确保首次加载的时候数据正确展示
    accountForm.value = {
      fileList: [{ uid: '1', name: '账号头像', url: accountStore.account.avatar }],
      name: accountStore.account.name,
      avatar: accountStore.account.avatar,
      password: '',
      email: accountStore.account.email,
    }
  },
)
</script>

<template>
  <a-modal :visible="visible" hide-title :footer="false" :width="1000" @cancel="handleCancel">
    <!-- 关闭按钮 -->
    <a-button
      type="text"
      class="!text-gray-700 absolute right-5 top-5"
      size="small"
      @click="handleCancel"
    >
      <template #icon>
        <icon-close />
      </template>
    </a-button>
    <!-- 内容容器 -->
    <div class="flex min-h-[500px]">
      <!-- 左侧导航 -->
      <div class="w-[200px] border-r pr-5">
        <!-- 导航版标题 -->
        <div class="text-xl font-bold text-gray-900 mb-5">设置</div>
        <!-- 导航列表 -->
        <div class="flex flex-col gap-2">
          <div
            class="cursor-pointer rounded-lg h-8 leading-8 px-4"
            :class="
              activeMenu === 'account'
                ? 'bg-gray-100 text-gray-900'
                : 'text-gray-700 hover:bg-gray-200 hover:text-gray-900'
            "
            data-testid="setting-menu-account"
            @click="activeMenu = 'account'"
          >
            账号设置
          </div>
          <div
            class="cursor-pointer rounded-lg h-8 leading-8 px-4"
            :class="
              activeMenu === 'model_provider'
                ? 'bg-gray-100 text-gray-900'
                : 'text-gray-700 hover:bg-gray-200 hover:text-gray-900'
            "
            data-testid="setting-menu-model-provider"
            @click="activeMenu = 'model_provider'"
          >
            大模型设置
          </div>
          <div
            class="cursor-pointer rounded-lg h-8 leading-8 px-4"
            :class="
              activeMenu === 'speech_provider'
                ? 'bg-gray-100 text-gray-900'
                : 'text-gray-700 hover:bg-gray-200 hover:text-gray-900'
            "
            data-testid="setting-menu-speech-provider"
            @click="activeMenu = 'speech_provider'"
          >
            语音服务
          </div>
        </div>
      </div>
      <!-- 右侧内容 -->
      <div v-if="activeMenu === 'account'" class="flex-1 px-8">
        <!-- 右侧标题 -->
        <div class="text-xl font-bold text-gray-700 mb-5">账号设置</div>
        <!-- 账号表单 -->
        <a-form :model="{}" layout="vertical">
          <a-form-item field="avatar">
            <template #label>
              <div class="flex items-center gap-1">
                账号头像
                <div class="text-red-700">*</div>
              </div>
            </template>
            <a-upload
              v-model:file-list="accountForm.fileList"
              list-type="picture-card"
              :limit="1"
              image-preview
              :custom-request="
                (option) => {
                  const uploadTask = async () => {
                    // 1.提取数据并发起请求获取响应内容
                    const { fileItem, onSuccess } = option
                    await handleUploadImage(fileItem.file as File)
                    accountForm.avatar = image_url
                    onSuccess(image_url)

                    // 2.更新账号头像
                    await handleUpdateAvatar(String(accountForm.avatar))

                    // 3.更新账号信息
                    await updateAccount()
                  }

                  uploadTask()

                  return {}
                }
              "
            />
          </a-form-item>
          <a-form-item field="name">
            <template #label>
              <div class="flex items-center gap-1">
                账号昵称
                <div class="text-red-700">*</div>
              </div>
            </template>
            <div v-if="updateName" class="flex items-center gap-2 w-full">
              <!-- 左侧输入框 -->
              <a-input
                v-model="accountForm.name"
                placeholder="请输入账号名称"
                :default-value="accountStore.account.name"
              />
              <!-- 取消&保存 -->
              <div class="flex items-center gap-1">
                <a-button
                  class="rounded-lg"
                  @click="
                    () => {
                      updateName = false
                      accountForm.name = accountStore.account.name
                    }
                  "
                >
                  取消
                </a-button>
                <a-button
                  type="primary"
                  class="rounded-lg"
                  @click="
                    async () => {
                      // 发起请求更新账号名称
                      await handleUpdateName(accountForm.name)

                      // 成功更新则重新获取账号数据并隐藏输入框
                      await updateAccount()
                      updateName = false
                    }
                  "
                >
                  保存
                </a-button>
              </div>
            </div>
            <div v-else class="flex items-center gap-1">
              <div class="">{{ accountStore.account.name }}</div>
              <a-button size="mini" type="text" class="!text-gray-700" @click="updateName = true">
                <template #icon>
                  <icon-edit />
                </template>
              </a-button>
            </div>
          </a-form-item>
          <a-form-item field="password">
            <template #label>
              <div class="flex items-center gap-1">
                账号密码
                <div class="text-red-700">*</div>
              </div>
            </template>
            <div v-if="updatePassword" class="flex items-center gap-2 w-full">
              <!-- 左侧输入框 -->
              <a-input-password v-model="accountForm.password" placeholder="请输入账号密码" />
              <!-- 取消&保存 -->
              <div class="flex items-center gap-1">
                <a-button
                  class="rounded-lg"
                  @click="
                    () => {
                      updatePassword = false
                      accountForm.password = ''
                    }
                  "
                >
                  取消
                </a-button>
                <a-button
                  type="primary"
                  class="rounded-lg"
                  @click="
                    async () => {
                      // 发起请求更新账号密码
                      await handleUpdatePassword(accountForm.password)

                      // 隐藏输入框并将输入框值清空
                      accountForm.password = ''
                      updatePassword = false
                    }
                  "
                >
                  保存
                </a-button>
              </div>
            </div>
            <div v-else class="flex items-center gap-1">
              <div class="">******</div>
              <a-button
                size="mini"
                type="text"
                class="!text-gray-700"
                @click="updatePassword = true"
              >
                <template #icon>
                  <icon-edit />
                </template>
              </a-button>
            </div>
          </a-form-item>
          <a-form-item field="email" label="绑定邮箱">
            <a-input readonly v-model="accountForm.email" />
          </a-form-item>
        </a-form>
      </div>
      <!-- 大模型设置 -->
      <div v-else-if="activeMenu === 'model_provider'" class="flex-1 px-8" data-testid="model-provider-setting">
        <!-- 右侧标题 -->
        <div class="text-xl font-bold text-gray-700 mb-5">大模型设置</div>
        <!-- 大模型设置表单 -->
        <a-form :model="modelForm" layout="vertical">
          <a-form-item field="base_url">
            <template #label>
              <div class="flex items-center gap-1">
                API 地址
                <div class="text-red-700">*</div>
              </div>
            </template>
            <a-input
              v-model="modelForm.base_url"
              placeholder="请输入模型服务地址，例如：https://token.uino.com/v1"
              data-testid="model-provider-base-url"
            />
          </a-form-item>
          <a-form-item field="api_key">
            <template #label>
              <div class="flex items-center gap-1">API Key</div>
            </template>
            <div v-if="updateApiKey" class="flex items-center gap-2 w-full">
              <a-input-password
                v-model="modelForm.api_key"
                placeholder="请输入新的 API Key，留空则保持原有密钥不变"
                data-testid="model-provider-api-key-input"
              />
              <a-button
                class="rounded-lg"
                @click="
                  () => {
                    updateApiKey = false
                    modelForm.api_key = ''
                  }
                "
              >
                取消
              </a-button>
            </div>
            <div v-else class="flex items-center gap-1">
              <div
                class="select-none tracking-widest text-gray-900"
                data-testid="model-provider-api-key-mask"
              >
                {{ modelSetting.has_api_key ? '****' : '未配置' }}
              </div>
              <a-button
                size="mini"
                type="text"
                class="!text-gray-700"
                data-testid="model-provider-api-key-edit"
                @click="updateApiKey = true"
              >
                <template #icon>
                  <icon-edit />
                </template>
              </a-button>
            </div>
          </a-form-item>
          <a-form-item field="source" label="配置来源">
            <div class="text-gray-700" data-testid="model-provider-source">
              {{ modelSetting.source_label || '-' }}
            </div>
          </a-form-item>
          <a-form-item>
            <div class="flex items-center gap-2">
              <a-button data-testid="model-provider-test" @click="handleTestModelProvider">
                测试连接
              </a-button>
              <a-button
                type="primary"
                class="rounded-lg"
                data-testid="model-provider-save"
                @click="handleSaveModelProvider"
              >
                保存
              </a-button>
            </div>
          </a-form-item>
        </a-form>
        <div class="text-xs text-gray-500 leading-5">
          说明：API
          Key保存后仅显示****，不可查看与复制；密钥留空保存表示只修改地址。配置保存后无需重启服务即可生效。
        </div>
      </div>
      <!-- 语音服务（CR-16102803） -->
      <div v-else class="flex-1 px-8 pb-6" data-testid="speech-provider-setting">
        <div class="text-xl font-bold text-gray-700 mb-5">语音服务</div>
        <a-form :model="speechForm" layout="vertical">
          <a-form-item field="engine">
            <template #label>
              <div class="flex items-center gap-1">
                语音引擎
                <div class="text-red-700">*</div>
              </div>
            </template>
            <a-select
              v-model="speechForm.engine"
              data-testid="speech-engine-select"
              placeholder="请选择语音引擎"
            >
              <a-option
                v-for="item in speechSetting.engines"
                :key="item.value"
                :value="item.value"
                :label="item.label"
              />
            </a-select>
            <div class="text-xs text-gray-500 leading-5 mt-1">
              浏览器：零成本、零网络，Chrome/Edge 可用；Omni-Realtime：一句话一次连接，按音频计费；
              CosyVoice + Paraformer：专用语音模型，识别需要 HTTPS 或 localhost。
            </div>
          </a-form-item>

          <a-form-item v-if="speechForm.engine !== 'browser'" field="dashscope_api_key">
            <template #label>
              <div class="flex items-center gap-1">
                阿里百炼 API Key
                <div class="text-red-700">*</div>
              </div>
            </template>
            <div class="flex items-center gap-2">
              <a-input
                v-if="updateSpeechKey || !speechSetting.has_api_key"
                v-model="speechForm.dashscope_api_key"
                placeholder="请输入阿里百炼 API Key"
                data-testid="speech-api-key-input"
                allow-clear
              />
              <div v-else class="flex-1" data-testid="speech-api-key-mask">
                <a-input :model-value="speechSetting.masked_api_key" readonly />
              </div>
              <a-button
                v-if="speechSetting.has_api_key && !updateSpeechKey"
                data-testid="speech-api-key-edit"
                @click="updateSpeechKey = true"
              >
                修改
              </a-button>
            </div>
            <div class="text-xs text-gray-500 leading-5 mt-1">
              密钥加密存储、仅显示掩码；留空保存表示不修改。当前来源：{{ speechSetting.source_label }}
            </div>
          </a-form-item>

          <template v-if="speechForm.engine === 'omni'">
            <a-form-item field="omni_model" label="Omni 模型">
              <a-input v-model="speechForm.omni_model" data-testid="speech-omni-model" />
            </a-form-item>
            <a-form-item field="omni_host" label="Realtime 域名">
              <a-input v-model="speechForm.omni_host" data-testid="speech-omni-host" />
              <div class="text-xs text-gray-500 leading-5 mt-1">
                业务空间专属域名（形如 xxx.cn-beijing.maas.aliyuncs.com），不是通用域名
              </div>
            </a-form-item>
            <a-form-item field="omni_voice" label="音色">
              <a-select v-model="speechForm.omni_voice" data-testid="speech-omni-voice">
                <a-option
                  v-for="voice in speechSetting.omni_voice_options"
                  :key="voice"
                  :value="voice"
                  :label="voice"
                />
              </a-select>
            </a-form-item>
          </template>

          <template v-if="speechForm.engine === 'dashscope'">
            <a-form-item field="cosyvoice_model" label="CosyVoice 模型">
              <a-input v-model="speechForm.cosyvoice_model" data-testid="speech-cosyvoice-model" />
            </a-form-item>
            <a-form-item field="cosyvoice_voice" label="CosyVoice 音色">
              <a-select v-model="speechForm.cosyvoice_voice" data-testid="speech-cosyvoice-voice">
                <a-option
                  v-for="voice in speechSetting.cosyvoice_voice_options"
                  :key="voice"
                  :value="voice"
                  :label="voice"
                />
              </a-select>
            </a-form-item>
            <a-form-item field="paraformer_model" label="Paraformer 模型（语音识别）">
              <a-input v-model="speechForm.paraformer_model" data-testid="speech-paraformer-model" />
            </a-form-item>
          </template>

          <a-form-item>
            <div class="flex items-center gap-3">
              <a-button type="primary" class="rounded-lg" data-testid="speech-save" @click="handleSaveSpeechProvider">
                保存
              </a-button>
              <a-button class="rounded-lg" data-testid="speech-test" @click="handleTestSpeechProvider">
                测试
              </a-button>
            </div>
          </a-form-item>
        </a-form>
        <div class="text-xs text-gray-500 leading-5">
          说明：保存后约 10 秒内生效（多进程各自缓存）。浏览器引擎不需要测试；测试专用引擎会真实合成两个字，产生极少量计费。
        </div>
      </div>
    </div>
  </a-modal>
</template>

<style scoped></style>
