import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { FilesystemConfirmation, GrantResourceEdit, RuntimeIdentity } from './types';
import { windowsPathLines } from './filesystemProfile';

const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
const resources: GrantResourceEdit = { tools: ['read_file'], network: [], filesystem: { read_only: ['C:\\Reports '], read_write: [] }, models: [] };
const confirmation: FilesystemConfirmation = { profile: 'windows-local-drive/v1', confirmed: true };
const legacyIdentity: RuntimeIdentity = {
  identity_id: 'ri-test', instance_id: 'hi-test', agent_id: 'hri-test', platform: 'hermes',
  grant_ref: { grant_id: 'gr-test', admission_id: 'adm-test', permission_digest: 'a'.repeat(64) },
  actor_id: 'reviewer', created_at: '2026-09-18T00:00:00Z', session_ttl_seconds: 3600, status: 'issued', runtime_state: 'unverified',
};
const windowsIdentity: RuntimeIdentity = { ...legacyIdentity, filesystem_profile: 'windows-local-drive/v1',
  grant_ref: { ...legacyIdentity.grant_ref, permission_digest_schema: 'grant-permissions/v2' } };
const issued = (identity = windowsIdentity) => ({ schema_version: 'local-runtime-identity-issued/v2', identity });
const sent = () => JSON.parse(String(vi.mocked(fetch).mock.calls[0]?.[1]?.body)) as Record<string, unknown>;

beforeEach(() => { vi.resetModules(); vi.stubGlobal('fetch', vi.fn()); });
afterEach(() => { vi.unstubAllGlobals(); });

describe('Windows authority request boundary', () => {
  it('defaults resources to v1 despite drive-looking paths, retaining the original value', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ grant: {}, state_revision: 4 }));
    await localApi.setGrantResources('gr-test', 3, 'reviewer', resources);
    expect(sent()).toEqual({ ...resources, schema_version: 'grant-resource-edit/v1', expected_revision: 3, actor_id: 'reviewer' });
    expect(sent()).not.toHaveProperty('confirm_filesystem_profile');
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('sends explicit v2 confirmation and preserves Windows aliases through JSON serialization', async () => {
    const { localApi } = await import('./api');
    const paths = ['C:\\Reports ', ' D:\\资料\\尾点.', 'E:\\MixedCase\\Sub  '];
    const edit = { ...resources, filesystem: { read_only: windowsPathLines(paths.join('\r\n')), read_write: [] } };
    vi.mocked(fetch).mockResolvedValueOnce(response({ grant: {}, state_revision: 4 }));
    await localApi.setGrantResources('gr-test', 3, 'reviewer', edit, confirmation);
    expect(sent()).toEqual({ ...edit, schema_version: 'grant-resource-edit/v2', expected_revision: 3, actor_id: 'reviewer', confirm_filesystem_profile: true });
    expect((sent().filesystem as GrantResourceEdit['filesystem']).read_only).toEqual(paths);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    { profile: 'windows-local-drive/v1' },
    { profile: 'windows-local-drive/v1', confirmed: false },
    { profile: 'windows-local-drive/v1', confirmed: 'true' },
    { profile: 'windows-local-drive/v2', confirmed: true },
  ])('rejects unconfirmed or unknown profile before either mutation: %j', async (bad) => {
    const { localApi } = await import('./api');
    const invalid = bad as unknown as FilesystemConfirmation;
    await expect(localApi.setGrantResources('gr-test', 3, 'reviewer', resources, invalid)).rejects.toMatchObject({ status: 400 });
    await expect(localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600, invalid)).rejects.toMatchObject({ status: 400 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('defaults identity creation to v1 without leaking a Windows confirmation', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ schema_version: 'local-runtime-identity-issued/v1', identity: legacyIdentity }));
    await localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600);
    expect(sent()).toEqual({ schema_version: 'local-runtime-identity-create/v1', instance_id: 'hi-test', grant_id: 'gr-test',
      expected_grant_revision: 3, actor_id: 'reviewer', session_ttl_seconds: 3600 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('binds explicitly confirmed identity creation to the requested instance, grant, and revision', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(issued()));
    await expect(localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600, confirmation)).resolves.toEqual(issued());
    expect(sent()).toEqual({ schema_version: 'local-runtime-identity-create/v2', instance_id: 'hi-test', grant_id: 'gr-test',
      expected_grant_revision: 3, actor_id: 'reviewer', session_ttl_seconds: 3600, confirm_filesystem_profile: true });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    { schema_version: 'local-runtime-identity-issued/v1', identity: legacyIdentity },
    issued(legacyIdentity),
    issued({ ...windowsIdentity, instance_id: 'hi-other' }),
    issued({ ...windowsIdentity, grant_ref: { ...windowsIdentity.grant_ref, grant_id: 'gr-other' } }),
    issued({ ...windowsIdentity, grant_ref: { ...windowsIdentity.grant_ref, permission_digest_schema: undefined } }),
  ])('rejects a substituted or downgraded identity without retrying issuance: %j', async (bad) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(bad));
    await expect(localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600, confirmation)).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(sent().schema_version).toBe('local-runtime-identity-create/v2');
  });

  it('does not silently upgrade a legacy request from a new-profile response', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(issued()));
    await expect(localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600)).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('refuses WorkBuddy POSIX identity creation before sending a request', async () => {
    const { localApi } = await import('./api');
    await expect(localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600, { profile: 'posix/v1' }, 'workbuddy')).rejects.toMatchObject({ status: 400 });
    expect(fetch).not.toHaveBeenCalled();
  });

  it('accepts the selected WorkBuddy platform without adding an untrusted platform request field', async () => {
    const { localApi } = await import('./api');
    const result = issued({ ...windowsIdentity, platform: 'workbuddy' });
    vi.mocked(fetch).mockResolvedValueOnce(response(result));
    await expect(localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600, confirmation, 'workbuddy')).resolves.toEqual(result);
    expect(sent()).not.toHaveProperty('platform');
    expect(sent().schema_version).toBe('local-runtime-identity-create/v2');
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each(['hermes', 'openclaw', 'unknown'] as const)('rejects a substituted platform %s without another issuance', async (platform) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(issued({ ...windowsIdentity, platform } as RuntimeIdentity)));
    await expect(localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600, confirmation, 'workbuddy')).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe('identity list profile compatibility', () => {
  it('accepts legacy v1 and a v2 envelope containing both generations', async () => {
    const { localApi } = await import('./api');
    for (const list of [
      { schema_version: 'local-runtime-identities/v1', items: [legacyIdentity] },
      { schema_version: 'local-runtime-identities/v2', items: [legacyIdentity, windowsIdentity] },
      { schema_version: 'local-runtime-identities/v2', items: [{ ...windowsIdentity, platform: 'workbuddy' }] },
    ]) {
      vi.mocked(fetch).mockResolvedValueOnce(response(list));
      await expect(localApi.runtimeIdentities()).resolves.toEqual(list);
    }
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it.each([
    { schema_version: 'local-runtime-identities/v1', items: [windowsIdentity] },
    { schema_version: 'local-runtime-identities/v3', items: [] },
    { schema_version: 'local-runtime-identities/v2', items: [{ ...windowsIdentity, grant_ref: legacyIdentity.grant_ref }] },
    { schema_version: 'local-runtime-identities/v2', items: [{ ...windowsIdentity, filesystem_profile: undefined }] },
    { schema_version: 'local-runtime-identities/v2', items: [null] },
    { schema_version: 'local-runtime-identities/v2', items: [{ ...legacyIdentity, platform: 'workbuddy' }] },
    { schema_version: 'local-runtime-identities/v1', items: [{ ...legacyIdentity, platform: 'workbuddy' }] },
    { schema_version: 'local-runtime-identities/v2', items: [{ ...windowsIdentity, platform: 'unknown' }] },
  ])('refuses contradictory or unknown metadata instead of displaying a legacy identity: %j', async (list) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response(list));
    await expect(localApi.runtimeIdentities()).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe('WorkBuddy managed capability comes from the service', () => {
  const catalog = { schema_version: 'local-adapter-instances/v2', platform_changes: false,
    native_available: false, managed_runtime_available: true, issues: [],
    instances: [{ instance_id: 'hi-test', platform: 'workbuddy' }] };

  it.each([true, false])('preserves the explicit managed availability %s without a fallback request', async (available) => {
    const { localApi } = await import('./api');
    const result = { ...catalog, managed_runtime_available: available };
    vi.mocked(fetch).mockResolvedValueOnce(response(result));
    await expect(localApi.adapterInstances('workbuddy')).resolves.toEqual(result);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    { schema_version: 'local-adapter-instances/v1' },
    { managed_runtime_available: undefined },
    { managed_runtime_available: 'true' },
    { platform_changes: true },
    { instances: [{ instance_id: 'hi-test', platform: 'codebuddy' }] },
    { instances: [{ instance_id: '', platform: 'workbuddy' }] },
    { instances: null },
    { issues: null },
  ])('rejects unverified capability or another platform: %j', async (bad) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ ...catalog, ...bad }));
    await expect(localApi.adapterInstances('workbuddy')).rejects.toMatchObject({ status: 502 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe('precise errors without automated recovery or fallback', () => {
  it.each(['resources', 'identity'])('surfaces the activation barrier on %s without another request', async (operation) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: 'windows_profile_activation_required', detail: 'private-state-path' }, 409));
    const attempt = operation === 'resources' ? localApi.setGrantResources('gr-test', 3, 'reviewer', resources, confirmation)
      : localApi.createRuntimeIdentity('hi-test', 'gr-test', 3, 'reviewer', 3600, confirmation);
    await expect(attempt).rejects.toMatchObject({ status: 409, code: 'windows_profile_activation_required', message: expect.stringContaining('state-status') });
    await expect(attempt).rejects.not.toThrow('private-state-path');
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['grant_filesystem_profile_invalid', 400],
    ['grant_filesystem_profile_confirmation_required', 409],
    ['grant_changed', 409],
  ] as const)('preserves %s instead of diagnosing every rejection as missing activation', async (code, status) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: code }, status));
    await expect(localApi.setGrantResources('gr-test', 3, 'reviewer', resources, confirmation)).rejects.toMatchObject({ status, code, message: code });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('keeps the existing global state compatibility diagnostic distinct from Windows activation', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: 'state_incompatible', detail: 'private-state-path' }, 503));
    const attempt = localApi.setGrantResources('gr-test', 3, 'reviewer', resources, confirmation);
    await expect(attempt).rejects.toMatchObject({ status: 503, message: expect.stringContaining('状态版本不兼容或迁移未完成') });
    await expect(attempt).rejects.toThrow('state-status');
    await expect(attempt).rejects.not.toThrow('Windows 路径授权');
    await expect(attempt).rejects.not.toThrow('private-state-path');
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('shows a transient snapshot diagnostic only for GET grants with exact 503 grants_busy', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: 'grants_busy' }, 503));
    await expect(localApi.grants()).rejects.toMatchObject({ status: 503, code: 'grants_busy', message: expect.stringContaining('授权正在更新') });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([['grants_busy', 500], ['grants_corrupt', 503]] as const)('does not hide a different snapshot failure: %s HTTP %s', async (code, status) => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: code }, status));
    await expect(localApi.grants()).rejects.toMatchObject({ status, code, message: code });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('does not relabel a mutation error as a busy list or retry it as v1', async () => {
    const { localApi } = await import('./api');
    vi.mocked(fetch).mockResolvedValueOnce(response({ error: 'grants_busy' }, 503));
    await expect(localApi.setGrantResources('gr-test', 3, 'reviewer', resources, confirmation)).rejects.toMatchObject({ status: 503, code: 'grants_busy', message: 'grants_busy' });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(sent().schema_version).toBe('grant-resource-edit/v2');
  });
});
