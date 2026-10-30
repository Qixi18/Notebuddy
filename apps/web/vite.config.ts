import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 后端代理目标可用 NB_API_TARGET 覆盖（如 8000 被占时切 8010），默认仍是 8000
const nodeProcess = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
const apiTarget = nodeProcess?.env?.NB_API_TARGET ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    watch: {
      // The editing tool writes atomic temp dirs next to source files on Windows.
      // Watching those transient paths can crash Vite with EBUSY.
      ignored: ['**/.*.tmpdir/**', '**/*.tmpdir/**'],
    },
    proxy: {
      '/api': apiTarget,
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          markdown: ['react-markdown', 'remark-math', 'rehype-katex', 'katex'],
        },
      },
    },
  },
})

