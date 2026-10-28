/**
 * @file use-stream-idle.ts
 * @desc CR-16102806 / FIX-1：流式响应的"静默计时"
 *
 * 背景：上游模型在长输出中途可能出现长时间无内容块的空窗（实测一次约 105 秒），
 *      期间后端每 10 秒发一次 ping 心跳，连接不断、也不报错，界面毫无变化，
 *      用户会误以为"已经输出完了但没结束"。
 *
 * 做法：用本地 1 秒粒度计时器测量"距上次收到内容块"的秒数，
 *      超过阈值即认为进入静默期，由界面给出"模型正在生成，已等待 N 秒"提示。
 *
 * 为什么不用 ping 事件驱动：
 *   1. ping 间隔固定 10 秒，精度太粗，20 秒阈值会抖动到 20~30 秒；
 *   2. 三处视图都得在事件分支里加处理，容易漏；
 *   3. 后端将来调整或去掉 ping 时，前端无需跟着改。
 */
import { computed, onBeforeUnmount, ref } from 'vue'

export const useStreamIdle = (threshold: number = 20) => {
  /** 距上次收到内容块的秒数 */
  const idleSeconds = ref(0)
  /** 是否已达到提示阈值 */
  const isIdle = computed(() => idleSeconds.value >= threshold)

  let timer: ReturnType<typeof setInterval> | null = null

  /** 停止计时并归零（请求结束 / 组件卸载时调用） */
  const stopIdleWatch = () => {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    idleSeconds.value = 0
  }

  /** 请求开始：归零并启动 1 秒粒度计时 */
  const startIdleWatch = () => {
    stopIdleWatch()
    timer = setInterval(() => {
      idleSeconds.value += 1
    }, 1000)
  }

  /** 收到任意内容事件：计时归零（ping 不应调用本函数） */
  const touchActivity = () => {
    idleSeconds.value = 0
  }

  // 路由切走后必须清理，否则计时器泄漏且后台空转
  onBeforeUnmount(stopIdleWatch)

  return { idleSeconds, isIdle, startIdleWatch, touchActivity, stopIdleWatch }
}
