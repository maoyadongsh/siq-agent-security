import { beforeEach, expect, it, vi } from 'vitest';
import { parseDeviceCredentialStatus, readDeviceCredentialStatus, revokeDeviceCredential } from './deviceLifecycle';

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ get, post }));
const endpoint = '/environments/env-one/devices/edge-one';
const active = () => ({ schema_version: 'enterprise-device-credential-status/v1', environment_id: 'env-one',
  device_id: 'edge-one', status: 'active', revoked_at: null, runtime_permissions_changed: false });
const revoked = () => ({ ...active(), status: 'revoked', revoked_at: '2026-09-25T12:34:56.123456' });
beforeEach(() => { get.mockReset(); post.mockReset(); });

it('reads active and revoked without writes or inferring runtime effects', async () => {
  get.mockResolvedValueOnce(active()).mockResolvedValueOnce(revoked());
  expect(await readDeviceCredentialStatus('env-one', 'edge-one')).toEqual(active());
  expect(await readDeviceCredentialStatus('env-one', 'edge-one')).toEqual(revoked());
  expect(get).toHaveBeenNthCalledWith(1, `${endpoint}/credential-status`);
  expect(post).not.toHaveBeenCalled();
});

it('submits only the exact confirmed device with one write', async () => {
  post.mockResolvedValue(revoked());
  expect(await revokeDeviceCredential('env-one', 'edge-one', 'edge-one')).toEqual(revoked());
  expect(post).toHaveBeenCalledExactlyOnceWith(`${endpoint}/revoke`, {
    schema_version: 'enterprise-device-revoke/v1', confirm_device_id: 'edge-one',
  });
  expect(get).not.toHaveBeenCalled();
});

it.each(['', '..', '../other', 'x/y', 'a?tenant=x', 'x#fragment', ' x', 'x\n', 'x'.repeat(65)])(
  'rejects unsafe path identifier %j before transport', async id => {
    await expect(readDeviceCredentialStatus(id, 'edge-one')).rejects.toThrow();
    await expect(revokeDeviceCredential('env-one', id, id)).rejects.toThrow();
    expect(get).not.toHaveBeenCalled(); expect(post).not.toHaveBeenCalled();
  },
);

it('requires exact confirmation without trimming or coercion', async () => {
  await expect(revokeDeviceCredential('env-one', 'edge-one', 'edge-other')).rejects.toThrow();
  await expect(revokeDeviceCredential('env-one', 'edge-one', 'edge-one ')).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});

it.each([
  { environment_id: 'env-other' }, { device_id: 'edge-other' }, { runtime_permissions_changed: true },
  { schema_version: 'v0' }, { status: 'online' }, { revoked_at: null }, { revoked_at: '' },
  { revoked_at: 'invalid-time' }, { status: 'active' }, { credential: 'must-not-be-exposed' },
])('rejects mismatched or inconsistent response %j', patch => {
  expect(() => parseDeviceCredentialStatus({ ...revoked(), ...patch }, 'env-one', 'edge-one')).toThrow();
});

it.each([null, [], {}, Object.create(active())])('rejects incomplete or inherited fields', value => {
  expect(() => parseDeviceCredentialStatus(value, 'env-one', 'edge-one')).toThrow();
});

it('never accepts active as successful revocation and does not retry', async () => {
  post.mockResolvedValue(active());
  await expect(revokeDeviceCredential('env-one', 'edge-one', 'edge-one')).rejects.toThrow('未确认');
  expect(post).toHaveBeenCalledTimes(1); expect(get).not.toHaveBeenCalled();
});

it('keeps transport failure uncertain; only explicit readback performs a GET', async () => {
  post.mockRejectedValue(new Error('response lost'));
  await expect(revokeDeviceCredential('env-one', 'edge-one', 'edge-one')).rejects.toThrow('response lost');
  expect(post).toHaveBeenCalledTimes(1); expect(get).not.toHaveBeenCalled();
  get.mockResolvedValue(revoked());
  expect((await readDeviceCredentialStatus('env-one', 'edge-one')).status).toBe('revoked');
  expect(post).toHaveBeenCalledTimes(1);
});
