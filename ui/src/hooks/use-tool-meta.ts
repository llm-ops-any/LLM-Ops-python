import { ref } from 'vue'
import { getBuiltinTools } from '@/services/builtin-tool'
import { getWorkflowsWithPage } from '@/services/workflow'

// 工具元信息：workflow=系统工作流，builtin=内置工具
export interface ToolMeta {
  type: 'workflow' | 'builtin'
  label: string
}

// 模块级缓存：运行流程组件在每条消息中各渲染一份，这里保证全局只请求一次
const toolMetaMap = ref<Record<string, ToolMeta>>({})
let loaded = false
let loadingPromise: Promise<void> | null = null

export const useToolMeta = () => {
  const loadToolMeta = () => {
    if (loaded) return Promise.resolve()
    if (loadingPromise) return loadingPromise

    loadingPromise = (async () => {
      const metaMap: Record<string, ToolMeta> = {}

      // 1.系统工作流：LangChain中的工具名为 wf_{workflow.tool_call_name}，
      //   展示时替换成工作流名称，例如 wf_kuaidiniaochaxun -> 快递鸟快递查询
      try {
        let page = 1
        let totalPage = 1
        while (page <= totalPage && page <= 20) {
          // 说明：后端page_size取值范围为1-50，超出会返回校验错误，这里取上限50并逐页拉取
          const resp = await getWorkflowsWithPage({ current_page: page, page_size: 50 })
          const data: any = resp?.data || {}
          ;(data.list || []).forEach((workflow: any) => {
            metaMap[`wf_${workflow.tool_call_name}`] = {
              type: 'workflow',
              label: workflow.name,
            }
          })
          totalPage = data.paginator?.total_page || 1
          page += 1
        }
      } catch (e) {
        // 接口异常时降级展示原始工具名，不影响运行流程
      }

      // 2.内置工具：工具名为英文标识，映射成中文标签，例如 web_search -> 谷歌搜索
      try {
        const resp = await getBuiltinTools()
        ;(resp?.data || []).forEach((provider: any) => {
          ;(provider.tools || []).forEach((tool: any) => {
            if (!metaMap[tool.name]) {
              metaMap[tool.name] = { type: 'builtin', label: tool.label || tool.name }
            }
          })
        })
      } catch (e) {
        // 同上
      }

      toolMetaMap.value = metaMap
      loaded = true
    })()

    return loadingPromise
  }

  return { toolMeta: toolMetaMap, loadToolMeta }
}
