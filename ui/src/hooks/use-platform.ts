import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import { getWechatConfig, updateWechatConfig } from '@/services/platform'
import type { UpdateWechatConfigRequest } from '@/models/platform'

/**
 * CR-16102807：微信公众号配置读取
 * 状态（configured/unconfigured）由后端按「三项齐全 + 应用已发布」推导，前端只展示
 */
export const useGetWechatConfig = () => {
  const loading = ref(false)
  const wechat_config = ref<Record<string, any>>({})

  const loadWechatConfig = async (app_id: string) => {
    try {
      loading.value = true
      const resp = await getWechatConfig(app_id)
      wechat_config.value = resp.data
    } finally {
      loading.value = false
    }
  }

  return { loading, wechat_config, loadWechatConfig }
}

export const useUpdateWechatConfig = () => {
  const loading = ref(false)

  const handleUpdateWechatConfig = async (app_id: string, req: UpdateWechatConfigRequest) => {
    try {
      loading.value = true
      const resp = await updateWechatConfig(app_id, req)
      Message.success(resp.message)
    } finally {
      loading.value = false
    }
  }

  return { loading, handleUpdateWechatConfig }
}
