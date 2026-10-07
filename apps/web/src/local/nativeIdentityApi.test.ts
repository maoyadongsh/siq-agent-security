import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import type { RuntimeIdentity } from './types';

const native: { schema_version: string; items: RuntimeIdentity[] } = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-runtime-identities-native-v3.sample.json', import.meta.url), 'utf8'));

const response = (data: unknown) => new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
const item = native.items[0];
const { native_skill_policy: policy, ...legacy } = item;
const windows = { ...legacy, platform: 'workbuddy', filesystem_profile: 'windows-local-drive/v1', grant_ref: { ...legacy.grant_ref, permission_digest_schema: 'grant-permissions/v2' } };

beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', vi.fn()); });
afterEach(() => vi.unstubAllGlobals());

describe('native identity readback contracts', () => {
  it.each([native, { ...native, items: [legacy, item, windows] }, { ...native, items: [windows, item, legacy] }])('reads actual Go native metadata and mixed platforms without promoting runtime status', async (list) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(list));
    await expect(localApi.runtimeIdentities()).resolves.toEqual(list);
    expect(list.items.every((identity) => identity.runtime_state === 'unverified')).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    { schema_version: 'local-runtime-identities/v1', items: [item] },
    { schema_version: 'local-runtime-identities/v2', items: [item] },
    { ...native, items: [legacy] },
    { ...native, items: [{ ...item, native_skill_policy: null }] },
    { ...native, items: [{ ...item, native_skill_policy: {} }] },
    { ...native, items: [{ ...item, native_skill_policy: { ...policy, mode: 'optional' } }] },
    { ...native, items: [{ ...item, native_skill_policy: { ...policy, mode: true } }] },
    { ...native, items: [{ ...item, native_skill_policy: { ...policy, extra: true } }] },
    { ...native, items: [{ ...item, native_skill_policy: { ...policy, runtime_artifact_sha256: 'unknown' } }] },
    { ...native, items: [{ ...item, native_skill_policy: { ...policy, runtime_artifact_sha256: 'C'.repeat(64) } }] },
    { ...native, items: [{ ...item, platform: 'openclaw' }] },
    { ...native, items: [{ ...item, filesystem_profile: 'windows-local-drive/v1', grant_ref: windows.grant_ref }] },
    { ...native, items: [{ ...item, runtime_state: 'verified' }] },
    { ...native, items: [{ ...legacy, Native_Skill_Policy: policy }] },
    { ...native, items: [...Array(513).fill(item)] },
  ])('rejects missing, downgraded, contradictory or unbounded native metadata', async (list) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(list));
    await expect(localApi.runtimeIdentities()).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each(['local-runtime-identity-issued/v1', 'local-runtime-identity-issued/v3'])('does not reinterpret native issuance as an ordinary identity: %s', async (schema_version) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ schema_version, identity: item }));
    await expect(localApi.createRuntimeIdentity(item.instance_id, item.grant_ref.grant_id, 1, 'fixture-human', 300)).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
