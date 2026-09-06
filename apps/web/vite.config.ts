import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, URL } from 'node:url';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

const isLocal = process.env.VITE_APP === 'agentshield';
const localOutDir = fileURLToPath(new URL('../agentshield/internal/ui/embedded', import.meta.url));

/** Vite names the output after index.local.html; Go embed expects index.html. */
function renameLocalIndex(): Plugin {
  return {
    name: 'agentshield-rename-index',
    closeBundle() {
      if (!isLocal) return;
      const from = path.join(localOutDir, 'index.local.html');
      const to = path.join(localOutDir, 'index.html');
      if (fs.existsSync(from)) {
        fs.renameSync(from, to);
      }
    },
  };
}

/**
 * Local embed is go:embed'd into a single binary. @fontsource CSS lists
 * woff2 + woff; modern browsers only need woff2. Strip the woff fallback so
 * Noto Serif SC (and latin faces) do not double the artifact.
 * Enterprise `npm run build` is unchanged.
 */
function dropLegacyWoff(): Plugin {
  const woffSrc =
    /,\s*url\((['"]?)[^'")]+?\.woff\1\)\s*format\(\s*(['"])woff\2\s*\)/g;
  return {
    name: 'agentshield-drop-woff',
    enforce: 'pre',
    transform(code, id) {
      if (!isLocal || !id.includes('.css')) return null;
      const next = code.replace(woffSrc, '');
      if (next === code) return null;
      return { code: next, map: null };
    },
    generateBundle(_opts, bundle) {
      if (!isLocal) return;
      for (const file of Object.keys(bundle)) {
        if (file.endsWith('.woff') && !file.endsWith('.woff2')) {
          delete bundle[file];
        }
      }
    },
  };
}

/** `npm run dev:local` must SPA-fallback to index.local.html, not the enterprise index.html. */
function localDevSpaFallback(): Plugin {
  return {
    name: 'agentshield-local-spa',
    configureServer(server) {
      if (!isLocal) return;
      return () => {
        server.middlewares.use((req, _res, next) => {
          const url = (req.url ?? '').split('?')[0] ?? '';
          if (
            url.startsWith('/src/') ||
            url.startsWith('/@') ||
            url.startsWith('/node_modules') ||
            url.startsWith('/v1') ||
            url === '/ui-config.json' ||
            url === '/index.local.html' ||
            url === '/favicon.ico' ||
            /\.[a-zA-Z0-9]+$/.test(url)
          ) {
            next();
            return;
          }
          req.url = '/index.local.html';
          next();
        });
      };
    },
  };
}

// SIQ Agent Security Web 控制台 — Vite 配置
//
// 企业控制台：client 默认同源 /api/v1；本地开发由 proxy 转发到 Control API。
// AgentShield 本地模式：VITE_APP=agentshield，产物 embed 进 agentshield serve。
export default defineConfig({
  base: isLocal ? '/' : process.env.SIQ_AS_WEB_BASE || '/',
  plugins: [react(), dropLegacyWoff(), renameLocalIndex(), localDevSpaFallback()],
  server: {
    headers: {
      'Cache-Control': 'no-store, max-age=0',
    },
    proxy: isLocal
      ? {
          '/v1': { target: 'http://127.0.0.1:47611', changeOrigin: true },
          '/ui-config.json': { target: 'http://127.0.0.1:47611', changeOrigin: true },
        }
      : {
          '/api/iam': {
            target: 'http://127.0.0.1:10088',
            changeOrigin: true,
            rewrite: (p) => p.replace(/^\/api\/iam/, ''),
          },
          '/api/agent-security': {
            target: 'http://127.0.0.1:8600',
            changeOrigin: true,
            rewrite: (p) => p.replace(/^\/api\/agent-security/, '/api'),
          },
          '/api': {
            target: 'http://127.0.0.1:8600',
            changeOrigin: true,
          },
          '/health': {
            target: 'http://127.0.0.1:8600',
            changeOrigin: true,
          },
        },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: isLocal ? localOutDir : 'dist',
    emptyOutDir: true,
    sourcemap: false,
    rollupOptions: isLocal
      ? { input: fileURLToPath(new URL('./index.local.html', import.meta.url)) }
      : undefined,
  },
});
