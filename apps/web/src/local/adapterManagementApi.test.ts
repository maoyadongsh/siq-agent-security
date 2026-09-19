import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AdapterPlan } from './types';

beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', vi.fn()); });
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('adapter management request lifetime', () => {
  it.each(['preview', 'install', 'uninstall', 'recover'] as const)('keeps %s alive for the server budget, then cancels once', async (route) => {
    const { localApi } = await import('./api');
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementation((_path, init) => new Promise((_resolve, reject) => {
      signal = init?.signal as AbortSignal;
      signal.addEventListener('abort', () => reject(new DOMException('canceled', 'AbortError')), { once: true });
    }));
    const plan = { platform: 'hermes', action: route, plan_id: 'ap-example', plan_digest: 'digest' } as AdapterPlan;
    const promise = route === 'preview' ? localApi.adapterPreview('hermes', 'uninstall', 'hi-example', true)
      : route === 'recover' ? localApi.adapterRecover('hermes', 'hi-example') : localApi.adapterApply(plan);
    const outcome = promise.then(() => 'unexpected success', (err: unknown) => err);
    await vi.advanceTimersByTimeAsync(175000);
    expect(signal?.aborted).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(signal?.aborted).toBe(true);
    expect(await outcome).toMatchObject({ status: 0 });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not extend read-only adapter discovery', async () => {
    const { localApi } = await import('./api');
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    vi.mocked(fetch).mockImplementation((_path, init) => new Promise((_resolve, reject) => {
      signal = init?.signal as AbortSignal;
      signal.addEventListener('abort', () => reject(new DOMException('canceled', 'AbortError')), { once: true });
    }));
    const outcome = localApi.adapterInstances('hermes').catch((err: unknown) => err);
    await vi.advanceTimersByTimeAsync(7999);
    expect(signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    expect(signal?.aborted).toBe(true);
    expect(await outcome).toMatchObject({ status: 0 });
  });

  it('reports busy without automatically retrying a management operation', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ error: 'adapter_busy' }), { status: 429 }));
    await expect(localApi.adapterRecover('hermes', 'hi-example')).rejects.toMatchObject({ status: 429, code: 'adapter_busy' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
