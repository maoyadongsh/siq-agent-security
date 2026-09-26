import { readFileSync } from 'node:fs';
import { expect, it, vi } from 'vitest';
import { readDeviceCredentialStatus, revokeDeviceCredential } from '../src/api/deviceLifecycle';
const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('../src/api/client', () => ({ get, post }));

it('consumes unmodified isolated backend status, revocation and recovery responses', async () => {
  const file = process.env.SIQ_DEVICE_WIRE_OUTPUT;
  if (!file) throw new Error('SIQ_DEVICE_WIRE_OUTPUT must name a fresh isolated producer artifact');
  const wire = JSON.parse(readFileSync(file, 'utf8'));
  expect(wire.scope).toBe('isolated-testclient-sqlite-development-identities');
  get.mockResolvedValueOnce(wire.active).mockResolvedValueOnce(wire.recovered);
  post.mockResolvedValueOnce(wire.revoked);
  expect((await readDeviceCredentialStatus(wire.environment_id, wire.device_id)).status).toBe('active');
  const revoked = await revokeDeviceCredential(wire.environment_id, wire.device_id, wire.device_id);
  expect(revoked.status).toBe('revoked');
  expect(await readDeviceCredentialStatus(wire.environment_id, wire.device_id)).toEqual(revoked);
  expect(revoked.runtime_permissions_changed).toBe(false);
  expect(post).toHaveBeenCalledExactlyOnceWith(
    `/environments/${wire.environment_id}/devices/${wire.device_id}/revoke`,
    { schema_version: 'enterprise-device-revoke/v1', confirm_device_id: wire.device_id },
  );
  expect(get).toHaveBeenCalledTimes(2);
});
