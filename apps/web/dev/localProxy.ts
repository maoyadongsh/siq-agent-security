import type { ProxyOptions } from 'vite';

const target = 'http://127.0.0.1:47611';

// Translate only an exact browser Origin for this dev server. Foreign origins
// and Fetch Metadata remain intact so the loopback backend still rejects them.
export function backendOrigin(origin: string | undefined, host: string | undefined): string | undefined {
  if (!origin || !host) return origin;
  return origin === `http://${host}` ? target : origin;
}

export function localProxy(): ProxyOptions {
  return {
    target, changeOrigin: true,
    configure(proxy) {
      proxy.on('proxyReq', (outgoing, incoming) => {
        const origin = backendOrigin(incoming.headers.origin, incoming.headers.host);
        if (origin) outgoing.setHeader('Origin', origin);
      });
    },
  };
}
