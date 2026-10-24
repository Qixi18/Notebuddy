import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

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
      '/api': 'http://127.0.0.1:8000',
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

