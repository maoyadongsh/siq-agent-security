import { afterEach, describe, expect, it, vi } from 'vitest';

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules(); });

describe('development identity boundary', () => {
  it.each([
    { dev: false, prod: true, flag: 'true', expected: false },
    { dev: true, prod: true, flag: 'true', expected: false },
    { dev: true, prod: false, flag: 'false', expected: false },
    { dev: true, prod: false, flag: undefined, expected: false },
    { dev: true, prod: false, flag: 'true', expected: true },
  ])('guards headers for $dev/$prod/$flag', async ({ dev, prod, flag, expected }) => {
    vi.stubEnv('DEV', dev); vi.stubEnv('PROD', prod);
    vi.stubEnv('VITE_DEV_MODE', flag);
    vi.stubEnv('VITE_DEV_TENANT_ID', 'synthetic-dev-tenant');
    vi.stubEnv('VITE_DEV_USER_ID', 'synthetic-dev-user');
    vi.resetModules();
    const fetcher = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetcher);
    const client = await import('./client');
    client.setToken('synthetic-request-token');
    await client.request('/identity-fixture');
    const headers = new Headers(fetcher.mock.calls[0][1].headers);
    expect(headers.get('Authorization')).toBe('Bearer synthetic-request-token');
    for (const name of ['X-Dev-Tenant-Id', 'X-Dev-User-Id', 'X-Dev-Roles']) {
      expect(headers.has(name)).toBe(expected);
    }
  });
});

describe('session restoration uses the same development boundary', () => {
  it.each([false, true])('production=$prod ignores a development bypass', async (prod) => {
    vi.stubEnv('DEV', !prod); vi.stubEnv('PROD', prod); vi.stubEnv('VITE_DEV_MODE', 'true');
    vi.resetModules();
    const fetcher = vi.fn().mockResolvedValue(new Response('{}', { status: 401 }));
    vi.stubGlobal('fetch', fetcher);
    const { restoreSession } = await import('./session');
    expect(await restoreSession()).toBe(!prod);
    expect(fetcher).toHaveBeenCalledTimes(prod ? 1 : 0);
  });
});
