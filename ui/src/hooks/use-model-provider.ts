import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  getModelProvider,
  testModelProviderConnection,
  updateModelProvider,
} from '@/services/model-provider'
import { type ModelProviderSetting } from '@/models/model-provider'

// 获取大模型服务设置
export const useGetModelProvider = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const setting = ref<ModelProviderSetting>({
    base_url: '',
    has_api_key: false,
    masked_api_key: '',
    source: '',
    source_label: '',
  })

  // 2.定义加载数据处理器
  const loadSetting = async () => {
    try {
      loading.value = true
      const resp = await getModelProvider()
      setting.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, setting, loadSetting }
}

// 保存大模型服务设置
export const useUpdateModelProvider = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)

  // 2.定义保存处理器，apiKey为空表示不修改密钥
  const handleUpdateSetting = async (baseUrl: string, apiKey: string) => {
    try {
      loading.value = true
      const resp = await updateModelProvider(baseUrl, apiKey)
      Message.success('大模型设置已保存，新配置即时生效')
      return resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateSetting }
}

// 测试大模型服务连通性
export const useTestModelProviderConnection = () => {
  // 1.定义hooks所需数据
  const loading = ref(false)
  const result = ref<{ ok: boolean; status: number; message: string; model_count: number }>({
    ok: false,
    status: 0,
    message: '',
    model_count: 0,
  })

  // 2.定义测试处理器
  const handleTestConnection = async (baseUrl: string, apiKey: string) => {
    try {
      loading.value = true
      const resp = await testModelProviderConnection(baseUrl, apiKey)
      result.value = resp.data
      if (resp.data.ok) {
        Message.success(resp.data.message)
      } else {
        Message.error(resp.data.message)
      }
      return resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, result, handleTestConnection }
}
