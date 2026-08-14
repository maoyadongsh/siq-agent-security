import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// SIQ Agent Security Web 控制台 — Vite 配置
//
// client 默认使用同源 /api/v1；本地开发由下方 proxy 转发到 Control API。
export default defineConfig({
  plugins: [react()],
  server: {
    headers: {
      'Cache-Control': 'no-store, max-age=0',
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8600',
        changeOrigin: true,
      },
    },
  },
  resolve: {
    alias: {
      // 与 tsconfig.json paths 保持一致
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    // Phase 1 骨架构建产物，按需调整
    outDir: 'dist',
    sourcemap: false,
  },
});
