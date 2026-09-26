import { beforeEach, expect, it, vi } from 'vitest';
import { parseRevokeOptions, proposeNetworkRevoke, readRevokeRecovery } from './networkRevoke';
const post = vi.hoisted(() => vi.fn());
const get = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ post, get }));
const raw = { schema_version: 'enterprise-network-revoke-options/v1', policy_id: 'p1', policy_version: 2, baseline_digest: 'a'.repeat(64), selections: [{ endpoint: 'a.example:443', binary_path: '/bin/a' }], coverage: 'complete_policy_network' };
beforeEach(() => { post.mockReset(); get.mockReset(); });
it.each([{ policy_id: 'other' }, { policy_version: 0 }, { baseline_digest: 'bad' }, { coverage: 'all_runtime' }, { selections: [...raw.selections, ...raw.selections] }, { selections: [{}] }, { raw_secret: 'no' }])('rejects unsafe options %j', patch => {
  expect(() => parseRevokeOptions({ ...raw, ...patch }, 'p1')).toThrow();
});
it('rejects selections outside snapshot before posting', async () => {
  await expect(proposeNetworkRevoke(parseRevokeOptions(raw, 'p1'), [{ endpoint: 'other:443', binary_path: '/bin/a' }], 'key')).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});
it('retains no-execution result and exact request binding', async () => {
  post.mockResolvedValue({ schema_version: 'enterprise-network-revoke-proposal-result/v1', source_policy_id: 'p1', policy_id: 'p2', change_request_id: 'c2', requires_independent_approval: true, executed: false });
  const options = parseRevokeOptions(raw, 'p1');
  expect((await proposeNetworkRevoke(options, options.selections, 'key')).executed).toBe(false);
  expect(post).toHaveBeenCalledExactlyOnceWith('/policies/p1/network-revoke-proposals', {
    schema_version: 'enterprise-network-revoke-proposal/v1', baseline_digest: raw.baseline_digest, request_key: 'key', selections: raw.selections,
  });
});
it('does not retry lost response automatically', async () => {
  post.mockRejectedValue(new Error('timeout'));
  await expect(proposeNetworkRevoke(parseRevokeOptions(raw, 'p1'), raw.selections, 'same-key')).rejects.toThrow();
  expect(post).toHaveBeenCalledTimes(1);
});
it('recovers current status by GET only', async () => {
  get.mockResolvedValue({ schema_version: 'enterprise-network-revoke-recovery/v1', source_policy_id: 'p1', policy_id: 'p2', change_request_id: 'c1', change_status: 'failed', lookup_executed: false });
  expect((await readRevokeRecovery('p1', '11111111-1111-4111-8111-111111111111')).change_status).toBe('failed');
  expect(get).toHaveBeenCalledExactlyOnceWith('/policies/p1/network-revoke-proposals/11111111-1111-4111-8111-111111111111');
  expect(post).not.toHaveBeenCalled();
});
it('rejects malformed recovery identifiers before any request', async () => {
  await expect(readRevokeRecovery('p1', '../invalid')).rejects.toThrow();
  expect(get).not.toHaveBeenCalled();
  expect(post).not.toHaveBeenCalled();
});
it.each([{ source_policy_id: 'other' }, { lookup_executed: true }, { raw_policy: {} }])('rejects inconsistent recovery %j', patch => {
  get.mockResolvedValue({ schema_version: 'enterprise-network-revoke-recovery/v1', source_policy_id: 'p1', policy_id: 'p2', change_request_id: 'c1', change_status: 'proposed', lookup_executed: false, ...patch });
  return expect(readRevokeRecovery('p1', '11111111-1111-4111-8111-111111111111')).rejects.toThrow();
});
