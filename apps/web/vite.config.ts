import { fileURLToPath, URL } from 'node:url';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// SIQ Agent Security Web 控制台 — Vite 配置
//
// 开发代理（可选）：Phase 1 的 client 默认直连绝对地址
// `VITE_API_BASE`（默认 http://127.0.0.1:8600/api/v1），不需要代理即可工作。
// 若希望走同源相对路径（如 VITE_API_BASE=/api/v1），可启用下面的 proxy：
//
//   server: {
//     proxy: {
//       '/api': {
//         target: 'http://127.0.0.1:8600',
//         changeOrigin: true,
//       },
//     },
//   },
export default defineConfig({
  plugins: [react()],
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
