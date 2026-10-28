import { ref } from 'vue'
import { Message } from '@arco-design/web-vue'
import {
  audioToText,
  getSpeechProvider,
  messageToAudio,
  testSpeechProvider,
  updateSpeechProvider,
} from '@/services/audio'
import type {
  SpeechEngine,
  SpeechProviderSetting,
  UpdateSpeechProviderRequest,
} from '@/models/audio'

// ============================================================================
// 全局语音配置：三处聊天入口（首页/调试页/WebApp）都要知道当前引擎，
// 但没必要各自请求一次，故用模块级单例缓存（CR-16102803 / FR-01）
// ============================================================================
const defaultSetting: SpeechProviderSetting = {
  engine: 'browser',
  has_api_key: false,
  masked_api_key: '',
  omni_model: '',
  omni_voice: '',
  omni_host: '',
  cosyvoice_model: '',
  cosyvoice_voice: '',
  paraformer_model: '',
  source: '',
  source_label: '',
  engines: [],
  omni_voice_options: [],
  cosyvoice_voice_options: [],
}

const speechSetting = ref<SpeechProviderSetting>({ ...defaultSetting })
let loaded = false

// 获取语音服务配置（带单例缓存）
export const useSpeechProvider = () => {
  const loading = ref(false)

  // 强制刷新：保存配置后调用
  const loadSpeechSetting = async (force = false) => {
    if (loaded && !force) return speechSetting.value
    try {
      loading.value = true
      const resp = await getSpeechProvider()
      speechSetting.value = resp.data
      loaded = true
      return resp.data
    } finally {
      loading.value = false
    }
  }

  // 保存配置：只传要改的字段
  const saveSpeechSetting = async (req: UpdateSpeechProviderRequest) => {
    loading.value = true
    try {
      const resp = await updateSpeechProvider(req)
      speechSetting.value = resp.data
      loaded = true
      Message.success('语音服务设置已保存')
      return resp.data
    } finally {
      loading.value = false
    }
  }

  // 测试当前引擎能否出声
  const testSpeechSetting = async () => {
    loading.value = true
    try {
      const resp = await testSpeechProvider()
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

  return { loading, setting: speechSetting, loadSpeechSetting, saveSpeechSetting, testSpeechSetting }
}

// 便捷：只取当前引擎（用于决定麦克风/播放走哪条路）
export const useSpeechEngine = () => {
  const engine = ref<SpeechEngine>('browser')
  const ensure = async () => {
    const resp = await getSpeechProvider().catch(() => null)
    if (resp?.data) engine.value = resp.data.engine
    return engine.value
  }
  return { engine, ensure }
}

// ============================================================================
// 播放：三档分派（CR-16102803 / FR-02 / FR-03 / FR-04）
//   browser   → speechSynthesis（零网络，AC-03）
//   omni      → SSE 收 base64 PCM 24k，Web Audio 顺序播放
//   dashscope → 同上（CosyVoice 也统一出 24k PCM）
// ============================================================================
export const useAudioPlayer = () => {
  const loading = ref(false)
  const isPlaying = ref(false)
  const errorMessage = ref('')
  const engine = ref<SpeechEngine>('browser')

  // 当前播放上下文（非响应式，放闭包外便于 stop 清理）
  let audioContext: AudioContext | null = null
  let sources: AudioBufferSourceNode[] = []
  let endTimer: number | null = null

  // 清理所有播放资源
  const cleanup = () => {
    if (endTimer !== null) {
      window.clearTimeout(endTimer)
      endTimer = null
    }
    sources.forEach((item) => {
      try {
        item.stop()
        item.disconnect()
      } catch {
        // 已结束的音源 stop 会抛错，忽略
      }
    })
    sources = []
    if (audioContext) {
      audioContext.close().catch(() => {})
      audioContext = null
    }
    isPlaying.value = false
  }

  const stop = () => {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel()
    }
    cleanup()
  }

  // base64 → Int16 PCM → Float32
  const decodePcm = (base64: string): Float32Array => {
    const binary = atob(base64)
    const bytes = new Uint8Array(binary.length)
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index)
    }
    const view = new DataView(bytes.buffer)
    // 16bit 小端，每 2 字节一个采样点
    const samples = Math.floor(bytes.byteLength / 2)
    const result = new Float32Array(samples)
    for (let index = 0; index < samples; index += 1) {
      result[index] = view.getInt16(index * 2, true) / 32768
    }
    return result
  }

  // 把一段 PCM 排进播放队列，保证连续不断音
  let nextPlayTime = 0
  const schedule = (pcm: Float32Array, sampleRate: number) => {
    if (!audioContext) audioContext = new AudioContext()
    const buffer = audioContext.createBuffer(1, Math.max(pcm.length, 1), sampleRate)
    buffer.copyToChannel(pcm, 0)
    const source = audioContext.createBufferSource()
    source.buffer = buffer
    source.connect(audioContext.destination)
    const startAt = Math.max(nextPlayTime, audioContext.currentTime)
    source.start(startAt)
    nextPlayTime = startAt + buffer.duration
    sources.push(source)
    source.onended = () => {
      const index = sources.indexOf(source)
      if (index >= 0) sources.splice(index, 1)
    }
  }

  /**
   * 播放一条消息
   * @param text 消息正文（browser 档要用它调 speechSynthesis）
   * @param messageId 消息 id（服务端档要用它取归属校验）
   */
  const play = async (text: string, messageId: string) => {
    errorMessage.value = ''
    if (isPlaying.value) {
      stop()
      return
    }

    const currentEngine = await useSpeechEngine().ensure()
    engine.value = currentEngine

    // 1.浏览器档：直接系统朗读，不产生任何后端请求（AC-03）
    if (currentEngine === 'browser') {
      if (!window.speechSynthesis) {
        Message.error('当前浏览器不支持系统朗读，请切换语音引擎')
        return
      }
      const utterance = new SpeechSynthesisUtterance(text)
      utterance.lang = 'zh-CN'
      utterance.onstart = () => {
        isPlaying.value = true
      }
      utterance.onend = () => {
        isPlaying.value = false
      }
      utterance.onerror = () => {
        isPlaying.value = false
      }
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(utterance)
      return
    }

    // 2.服务端档：SSE 收 PCM 流式播放
    try {
      loading.value = true
      nextPlayTime = 0
      await messageToAudio(messageId, (eventResponse) => {
        const event = eventResponse?.event
        const data = eventResponse?.data
        if (event === 'tts_message' && data?.audio) {
          isPlaying.value = true
          schedule(decodePcm(data.audio), data.sample_rate || 24000)
        } else if (event === 'tts_error') {
          // 流式开始后失败只能靠事件告知，见后端设计 §八
          errorMessage.value = data?.message || '语音合成失败'
          Message.error(errorMessage.value)
          cleanup()
        } else if (event === 'tts_end') {
          // 用最后一段的结束时刻兜底收状态，避免按钮一直显示“播放中”
          const wait = Math.max(0, (nextPlayTime - (audioContext?.currentTime || 0)) * 1000)
          endTimer = window.setTimeout(() => {
            isPlaying.value = false
          }, wait + 300)
        }
      })
    } catch (error: any) {
      // ssePost 在 JSON 响应（业务错误）时会直接把 json 返回，这里统一兜住
      const message = error?.message || '语音播放失败，请稍后重试'
      errorMessage.value = message
      Message.error(message)
      cleanup()
    } finally {
      loading.value = false
    }
  }

  return { loading, isPlaying, errorMessage, engine, play, stop }
}

// ============================================================================
// 录音：Web Audio 采集 → 16k 单声道 WAV
// 为什么不用 MediaRecorder：Chrome 只能出 webm，而 Paraformer 不支持 webm 容器
// （CR-16102803 / D-12）；自己封装 WAV 零依赖，采样率也可控。
// ============================================================================
const mergeChunks = (chunks: Float32Array[]): Float32Array => {
  const total = chunks.reduce((sum, item) => sum + item.length, 0)
  const merged = new Float32Array(total)
  let offset = 0
  chunks.forEach((item) => {
    merged.set(item, offset)
    offset += item.length
  })
  return merged
}

// 线性插值重采样到 16k
const resampleTo16k = (input: Float32Array, fromRate: number): Float32Array => {
  const targetRate = 16000
  if (fromRate === targetRate) return input
  const ratio = fromRate / targetRate
  const length = Math.floor(input.length / ratio)
  const output = new Float32Array(length)
  for (let index = 0; index < length; index += 1) {
    const position = index * ratio
    const low = Math.floor(position)
    const high = Math.min(low + 1, input.length - 1)
    const weight = position - low
    output[index] = input[low] * (1 - weight) + input[high] * weight
  }
  return output
}

// Float32(-1~1) → Int16 PCM → WAV 容器
const encodeWav = (samples: Float32Array, sampleRate: number): ArrayBuffer => {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  const writeText = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index))
    }
  }
  writeText(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeText(8, 'WAVE')
  writeText(12, 'fmt ')
  view.setUint32(16, 16, true) // PCM 块大小
  view.setUint16(20, 1, true) // PCM 格式
  view.setUint16(22, 1, true) // 单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // 字节率
  view.setUint16(32, 2, true) // 块对齐
  view.setUint16(34, 16, true) // 位深
  writeText(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  let offset = 44
  for (let index = 0; index < samples.length; index += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[index]))
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true)
    offset += 2
  }
  return buffer
}

export const useWavRecorder = () => {
  const recording = ref(false)
  let stream: MediaStream | null = null
  let context: AudioContext | null = null
  let source: MediaStreamAudioSourceNode | null = null
  let processor: ScriptProcessorNode | null = null
  let silence: GainNode | null = null
  let chunks: Float32Array[] = []
  let sourceRate = 44100

  // 开始录音
  const start = async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('当前浏览器不支持麦克风采集')
    }
    // 风险 R-08：非安全上下文取不到麦克风
    if (!window.isSecureContext && !['localhost', '127.0.0.1'].includes(window.location.hostname)) {
      throw new Error('录音需要 HTTPS 或 localhost 访问，请改用 https 或切换浏览器识别')
    }
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    })
    context = new AudioContext()
    sourceRate = context.sampleRate
    source = context.createMediaStreamSource(stream)
    processor = context.createScriptProcessor(4096, 1, 1)
    // 接一个 0 增益节点再到 destination：不接的话部分浏览器不回调，接了会外放回声
    silence = context.createGain()
    silence.gain.value = 0
    chunks = []
    processor.onaudioprocess = (event) => {
      if (!recording.value) return
      chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)))
    }
    source.connect(processor)
    processor.connect(silence)
    silence.connect(context.destination)
    recording.value = true
  }

  // 停止录音并返回 16k WAV
  const stop = async (): Promise<Blob | null> => {
    recording.value = false
    try {
      processor?.disconnect()
      source?.disconnect()
      silence?.disconnect()
      stream?.getTracks().forEach((track) => track.stop())
      await context?.close()
    } catch {
      // 资源释放失败不影响已采集的数据
    }
    const merged = mergeChunks(chunks)
    chunks = []
    processor = null
    source = null
    silence = null
    context = null
    stream = null
    if (merged.length === 0) return null
    const pcm16k = resampleTo16k(merged, sourceRate)
    return new Blob([encodeWav(pcm16k, 16000)], { type: 'audio/wav' })
  }

  return { recording, start, stop }
}

// 录音 → 服务端识别（仅 dashscope 档）
export const useAudioToText = () => {
  const loading = ref(false)
  const recorder = useWavRecorder()

  const recognize = async (blob: Blob): Promise<string> => {
    loading.value = true
    try {
      const resp = await audioToText(blob)
      return resp.data.text
    } finally {
      loading.value = false
    }
  }

  return { loading, recorder, recognize }
}
