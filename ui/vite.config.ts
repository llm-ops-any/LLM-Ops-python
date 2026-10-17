import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: {
      // 与 nginx 行为保持一致：/api/* → 后端 5001，并去掉 /api 前缀。
      // 仅在 VITE_API_PREFIX=/api 时才会走到这里（.env.development 默认直连 http://localhost:5001）。
      // http-proxy 默认流式转发，SSE 不会被攒批，无需额外关闭缓冲。
      '/api': {
        target: 'http://127.0.0.1:5001',
        changeOrigin: true,
        rewrite: (path: string) => path.replace(/^\/api/, ''),
      },
    },
  },
})
