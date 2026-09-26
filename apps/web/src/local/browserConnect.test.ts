import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

const id = 'b'.repeat(32);
const pending = { schema_version: 'local-browser-connect/v1', request_id: id, status: 'pending', expires_in: 299 };
const access = 'a'.repeat(64);
const session = { schema_version: 'local-admin-session/v2', session: access, expires_in: 86400, scope: 'admin' };
const response = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

describe('Skill-assisted browser connection', () => {
  beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', vi.fn()); });
  afterEach(() => vi.unstubAllGlobals());

  it('polls without bearer credentials and only installs a valid approved session', async () => {
    const { beginBrowserConnection, localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(pending)).mockResolvedValueOnce(response(pending)).mockResolvedValueOnce(response(session)).mockResolvedValueOnce(response({}));
    const connection = await beginBrowserConnection();
    expect(connection.requestId).toBe(id);
    await expect(connection.poll()).resolves.toBe(false);
    await expect(connection.poll()).resolves.toBe(true);
    for (const [url, init] of vi.mocked(fetch).mock.calls.slice(0, 3)) {
      expect(String(url)).not.toContain(id);
      expect(init?.credentials).toBe('same-origin');
      expect(new Headers(init?.headers).has('Authorization')).toBe(false);
    }
    await localApi.status();
    expect(new Headers(vi.mocked(fetch).mock.lastCall?.[1]?.headers).get('Authorization')).toBe(`Bearer ${access}`);
  });

  it('rejects legacy HTML, wrong IDs and a session exceeding 24 hours', async () => {
    const { beginBrowserConnection } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(new Response('<html>legacy</html>'));
    await expect(beginBrowserConnection()).rejects.toThrow('响应格式');
    vi.mocked(fetch).mockResolvedValueOnce(response(pending)).mockResolvedValueOnce(response({ ...pending, request_id: 'c'.repeat(32) })).mockResolvedValueOnce(response({ ...session, expires_in: 86401 }));
    const connection = await beginBrowserConnection();
    await expect(connection.poll()).rejects.toThrow('不兼容');
    await expect(connection.poll()).rejects.toThrow('不兼容');
  });

  it('does not install a late session after cancellation', async () => {
    const { beginBrowserConnection } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(pending));
    const connection = await beginBrowserConnection();
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const poll = connection.poll();
    vi.mocked(fetch).mockResolvedValueOnce(response({ ...pending, status: 'cancelled', expires_in: 0 }));
    await connection.cancel();
    finish(response(session));
    await expect(poll).rejects.toThrow('会话已更新');
  });

  it('does not replace a newer manually paired session', async () => {
    const { beginBrowserConnection, pair } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(pending));
    const connection = await beginBrowserConnection();
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    const poll = connection.poll();
    vi.mocked(fetch).mockResolvedValueOnce(response(session));
    await pair('aaaa-bbbb-cccc-dddd');
    finish(response(session));
    await expect(poll).rejects.toThrow('会话已更新');
  });

  it('keeps expired requests unconnected', async () => {
    const { beginBrowserConnection } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(pending)).mockResolvedValueOnce(response({}, 410));
    const connection = await beginBrowserConnection();
    await expect(connection.poll()).rejects.toThrow('已过期');
  });
});
