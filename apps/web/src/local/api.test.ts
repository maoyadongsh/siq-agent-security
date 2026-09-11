import { readFileSync } from "node:fs";
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const access = 'a'.repeat(64);
const sessionResponse = { schema_version: 'local-admin-session/v1', session: access, expires_in: 43200, scope: 'admin' };
const config = {
  schema_version: 'local-ui-config/v1', product: 'siq-agent-security', version: 'test',
  local_mode: true, single_user: true, enforcement_mode: 'block', session_recovery: true, pairing_available: false,
};
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });

describe('local session recovery', () => {
  beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', vi.fn()); });
  afterEach(() => { vi.unstubAllGlobals(); });

  it('validates the service identity and rejects an HTML fallback or credential leak', async () => {
    const { boot } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(config));
    await expect(boot()).resolves.toEqual(config);
    vi.mocked(fetch).mockResolvedValueOnce(new Response('<html>enterprise</html>'));
    await expect(boot()).rejects.toThrow('响应格式不正确');
    vi.mocked(fetch).mockResolvedValueOnce(response({ ...config, token: 'secret' }));
    await expect(boot()).rejects.toThrow('返回了凭据');
    vi.mocked(fetch).mockResolvedValueOnce(response({ ...config, product: 'another-app' }));
    await expect(boot()).rejects.toThrow('不兼容');
  });

  it('pairs with an HttpOnly recovery cookie request and uses only the returned bearer for admin calls', async () => {
    const { pair, localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(sessionResponse)).mockResolvedValueOnce(response({ version: 'test' }));
    await pair('aaaa-bbbb-cccc-dddd');
    const init = vi.mocked(fetch).mock.calls[0]?.[1];
    expect(init?.credentials).toBe('same-origin');
    expect(new Headers(init?.headers).get('X-SIQ-Session')).toBe('1');
    expect(JSON.parse(String(init?.body))).toEqual({ code: 'aaaa-bbbb-cccc-dddd', remember: true });
    await localApi.status();
    expect(new Headers(vi.mocked(fetch).mock.calls[1]?.[1]?.headers).get('Authorization')).toBe(`Bearer ${access}`);
  });

  it('deduplicates restoration and treats expiry as a pairing state', async () => {
    const { restoreSession } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(sessionResponse));
    const a = restoreSession();
    const b = restoreSession();
    expect(a).toBe(b);
    await expect(a).resolves.toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: 'pairing required' }, 401));
    await expect(restoreSession()).resolves.toBe(false);
  });

  it('refuses an invalid session rather than treating it as restored', async () => {
    const { restoreSession } = await import('./api');
    for (const bad of [{ ...sessionResponse, scope: 'decision' }, { ...sessionResponse, expires_in: 43201 }, { ...sessionResponse, session: 'short' }]) {
      vi.mocked(fetch).mockResolvedValueOnce(response(bad));
      await expect(restoreSession()).rejects.toThrow('不兼容');
    }
  });

  it('does not restore an in-flight bearer after logout', async () => {
    const { pair, restoreSession, logout, localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(sessionResponse));
    await pair('code');
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockImplementationOnce(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const pending = restoreSession();
    vi.mocked(fetch).mockResolvedValueOnce(response({ schema_version: 'local-logout/v1', signed_out: true }));
    await logout();
    finish(response(sessionResponse));
    await expect(pending).resolves.toBe(false);
    vi.mocked(fetch).mockResolvedValueOnce(response({ version: 'test' }));
    await localApi.status();
    expect(new Headers(vi.mocked(fetch).mock.calls.at(-1)?.[1]?.headers).has('Authorization')).toBe(false);
  });

  it('reports expired admin authorization and never retries a mutation', async () => {
    const { pair, localApi, onSessionExpired } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(sessionResponse));
    await pair('code');
    const expired = vi.fn();
    const unsubscribe = onSessionExpired(expired);
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: 'unauthorized' }, 401));
    await expect(localApi.putConfig('warn')).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
    expect(fetch).toHaveBeenCalledTimes(2);
    unsubscribe();
  });

  it('gives a retry instruction when the service is unreachable', async () => {
    const { boot } = await import('./api');
    vi.mocked(fetch).mockRejectedValueOnce(new TypeError('Failed to fetch'));
    await expect(boot()).rejects.toThrow('siq-agent-security serve');
  });
});

describe('local import request lifetime', () => {
  beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', vi.fn()); });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  it('allows the import processing budget, then aborts once without retrying a write', async () => {
    const { localApi } = await import('./api');
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementationOnce((_url, init) => new Promise<Response>((_resolve, reject) => {
      signal = init?.signal ?? undefined;
      signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    }));
    const pending = localApi.createSkillImport({ schema_version: 'local-skill-import-create/v1', import_id: 'si-' + 'a'.repeat(32), source_kind: 'local_dir', path: '/fixture', actor_id: 'fixture' });
    const rejected = expect(pending).rejects.toMatchObject({ status: 0 });
    await vi.advanceTimersByTimeAsync(69999);
    expect(signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('propagates page cancellation and preserves the normal service request timeout', async () => {
    const { localApi } = await import('./api');
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation((_url, init) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    }));
    const controller = new AbortController();
    const pending = localApi.skillImports(controller.signal);
    const canceled = expect(pending).rejects.toMatchObject({ status: 0 });
    controller.abort();
    await canceled;
    const status = localApi.status();
    const timedOut = expect(status).rejects.toMatchObject({ status: 0 });
    await vi.advanceTimersByTimeAsync(8000);
    await timedOut;
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});


describe('remote Skill import routing', () => {
  beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', vi.fn()); });
  afterEach(() => { vi.unstubAllGlobals(); });
  it('posts the exact remote request to the admin route and requires a matching v2 response', async () => {
    const { localApi } = await import('./api');
    const result = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-skill-import-result.v2.sample.json', import.meta.url), 'utf8'));
    const body = { schema_version: 'local-skill-import-remote-create/v1' as const, import_id: result.import.import_id,
      url: 'https://download.example.com/archive.zip?token=private', archive_path: 'repo/skill', expected_sha256: '', actor_id: 'fixture' };
    vi.mocked(fetch).mockResolvedValueOnce(response(result));
    await expect(localApi.createSkillImport(body)).resolves.toMatchObject({ installed: false });
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe('/v1/skill-imports/remote');
    expect(JSON.parse(String(vi.mocked(fetch).mock.calls[0][1]?.body))).toEqual(body);
    const legacy = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-skill-import-result.v1.sample.json', import.meta.url), 'utf8'));
    legacy.import.import_id = body.import_id;
    vi.mocked(fetch).mockResolvedValueOnce(response(legacy));
    await expect(localApi.createSkillImport(body)).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
