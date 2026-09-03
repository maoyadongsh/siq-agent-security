import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// SIQ Agent Security Web 控制台 — Vite 配置
//
// client 默认使用同源 /api/v1；本地开发由下方 proxy 转发到 Control API。
export default defineConfig({
  // 独立开发保持根路径；平台镜像构建传入 SIQ_AS_WEB_BASE=/agent-security/
  base: process.env.SIQ_AS_WEB_BASE || '/',
  plugins: [react()],
  server: {
    headers: {
      'Cache-Control': 'no-store, max-age=0',
    },
    proxy: {
      '/api/iam': {
        target: 'http://127.0.0.1:10088',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/iam/, ''),
      },
      '/api/agent-security': {
        target: 'http://127.0.0.1:8600',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/agent-security/, '/api'),
      },
      '/api': {
        target: 'http://127.0.0.1:8600',
        changeOrigin: true,
      },
      // 设置页连接状态探测用的无鉴权健康检查
      '/health': {
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
    // 生产构建输出；本地开发走上方 proxy
    outDir: 'dist',
    sourcemap: false,
  },
});
