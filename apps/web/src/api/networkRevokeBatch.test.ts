import { beforeEach, expect, it, vi } from 'vitest';
import { buildRevokeBatch, parseRevokeBatchResult, proposeRevokeBatch, readRevokeBatch, type BatchRevokeSelection } from './networkRevokeBatch';
const post = vi.hoisted(() => vi.fn());
const get = vi.hoisted(() => vi.fn());
vi.mock('./client', () => ({ post, get }));
const key = '11111111-1111-4111-8111-111111111111';
function input(id = 'p1', count = 1): BatchRevokeSelection {
  const selections = Array.from({ length: count }, (_, index) => ({ endpoint: `fixture${index}.example:443`, binary_path: '/bin/a' }));
  return { options: { schema_version: 'enterprise-network-revoke-options/v1', policy_id: id, policy_version: 1,
    baseline_digest: 'a'.repeat(64), coverage: 'complete_policy_network', selections }, selections };
}
function result() {
  return { schema_version: 'enterprise-network-revoke-batch-result/v1', executed: false, requires_independent_approval: true,
    items: ['p1', 'p2'].map(id => ({ schema_version: 'enterprise-network-revoke-proposal-result/v1', source_policy_id: id,
      policy_id: `${id}-new`, change_request_id: `${id}-change`, executed: false, requires_independent_approval: true })) };
}
function recovery() {
  return { schema_version: 'enterprise-network-revoke-batch-recovery/v1', lookup_executed: false,
    items: result().items.map(item => ({ source_policy_id: item.source_policy_id, policy_id: item.policy_id,
      change_request_id: item.change_request_id, change_status: 'proposed' })) };
}
beforeEach(() => { post.mockReset(); get.mockReset(); });

it('builds the exact contract without mutating selections or carrying identity', () => {
  const items = [input('p1'), input('p2')];
  const before = JSON.stringify(items);
  expect(buildRevokeBatch(items, key)).toEqual({ schema_version: 'enterprise-network-revoke-batch/v1', request_key: key,
    items: items.map(item => ({ policy_id: item.options.policy_id, baseline_digest: 'a'.repeat(64), selections: item.selections })) });
  expect(JSON.stringify(items)).toBe(before);
});
it.each(['../invalid', `${key}\n`, ''])('rejects invalid identifiers before any network call: %j', async value => {
  await expect(proposeRevokeBatch([input()], value)).rejects.toThrow();
  await expect(readRevokeBatch(value)).rejects.toThrow();
  expect(post).not.toHaveBeenCalled(); expect(get).not.toHaveBeenCalled();
});
it.each(['empty', 'duplicate', 'tooMany', 'total', 'outside', 'noSelection', 'duplicatePair', 'snapshot'])('rejects invalid input %s before POST', async kind => {
  let items = [input()];
  if (kind === 'empty') items = [];
  if (kind === 'duplicate') items.push(input());
  if (kind === 'tooMany') items = Array.from({ length: 21 }, (_, index) => input(`p${index}`));
  if (kind === 'total') items = [input('p1', 171), input('p2', 171), input('p3', 171)];
  if (kind === 'outside') items[0].selections = [{ endpoint: 'outside:443', binary_path: '/bin/a' }];
  if (kind === 'noSelection') items[0].selections = [];
  if (kind === 'duplicatePair') items[0].selections = [...items[0].selections, ...items[0].selections];
  if (kind === 'snapshot') items[0].options.baseline_digest = 'invalid';
  await expect(proposeRevokeBatch(items, key)).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});
it('accepts the exact 20 policy and 512 selection boundaries', () => {
  expect(buildRevokeBatch(Array.from({ length: 20 }, (_, i) => input(`p${i}`)), key).items).toHaveLength(20);
  expect(buildRevokeBatch([input('p1', 256), input('p2', 256)], key).items).toHaveLength(2);
});
it('validates all source mappings and uses one explicit POST', async () => {
  post.mockResolvedValue(result());
  const items = [input('p2'), input('p1')];
  expect(await proposeRevokeBatch(items, key)).toEqual(result());
  expect(post).toHaveBeenCalledExactlyOnceWith('/network-revoke-batches', buildRevokeBatch(items, key));
});
it.each(['missing', 'duplicateSource', 'foreign', 'duplicatePolicy', 'duplicateChange', 'sourceAsChild', 'executed', 'approved', 'extra'])('refuses ambiguous response %s', kind => {
  const value = result();
  if (kind === 'missing') value.items.pop();
  if (kind === 'duplicateSource') value.items[1].source_policy_id = 'p1';
  if (kind === 'foreign') value.items[1].source_policy_id = 'foreign';
  if (kind === 'duplicatePolicy') value.items[1].policy_id = value.items[0].policy_id;
  if (kind === 'duplicateChange') value.items[1].change_request_id = value.items[0].change_request_id;
  if (kind === 'sourceAsChild') value.items[1].policy_id = 'p1';
  if (kind === 'executed') value.items[0].executed = true;
  if (kind === 'approved') value.requires_independent_approval = false;
  if (kind === 'extra') Object.assign(value, { policy_body: {} });
  expect(() => parseRevokeBatchResult(value, ['p1', 'p2'])).toThrow();
});
it('does not retry a lost response or fall back to single-policy writes', async () => {
  post.mockRejectedValue(new Error('lost response'));
  await expect(proposeRevokeBatch([input()], key)).rejects.toThrow();
  expect(post).toHaveBeenCalledTimes(1); expect(get).not.toHaveBeenCalled();
});
it('reads independent current states without invoking a write', async () => {
  const value = recovery(); value.items[0].change_status = 'approved';
  get.mockResolvedValue(value);
  expect((await readRevokeBatch(key)).items.map(item => item.change_status)).toEqual(['approved', 'proposed']);
  expect(get).toHaveBeenCalledExactlyOnceWith(`/network-revoke-batches/${key}`);
  expect(post).not.toHaveBeenCalled();
});
it.each(['empty', 'duplicate', 'lookup', 'extra', 'status'])('refuses invalid recovery %s', async kind => {
  const value = recovery();
  if (kind === 'empty') value.items = [];
  if (kind === 'duplicate') value.items[1] = value.items[0];
  if (kind === 'lookup') value.lookup_executed = true;
  if (kind === 'extra') Object.assign(value.items[0], { selections: [] });
  if (kind === 'status') value.items[0].change_status = '';
  get.mockResolvedValue(value);
  await expect(readRevokeBatch(key)).rejects.toThrow();
  expect(post).not.toHaveBeenCalled();
});
