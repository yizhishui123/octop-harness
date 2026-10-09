import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: Number(process.env.VITE_PORT) || 5173,
    proxy: {
      '/api': process.env.VITE_API_TARGET || 'http://localhost:8000',
    },
  },
  build: {
    // markdown-it + highlight.js ship a fair amount of JS; the demo is fine with it.
    chunkSizeWarningLimit: 1500,
  },
})
