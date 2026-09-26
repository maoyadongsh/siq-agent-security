// Explicit cross-language check, not part of the default frontend unit-test glob.
import { readFileSync } from 'node:fs';
import { expect, it, vi } from 'vitest';
import { parseRevokeBatchResult, readRevokeBatch } from '../src/api/networkRevokeBatch';
const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock('../src/api/client', () => ({ get, post }));

it('accepts unmodified isolated Python HTTP responses with independent child states', async () => {
  const path = process.env.SIQ_REVOKE_BATCH_WIRE_OUTPUT;
  if (!path) throw new Error('SIQ_REVOKE_BATCH_WIRE_OUTPUT must identify the fresh isolated producer artifact');
  const wire = JSON.parse(readFileSync(path, 'utf8'));
  expect(wire.scope).toBe('isolated-testclient-sqlite-development-identities');
  const result = parseRevokeBatchResult(wire.proposal_response, wire.source_ids);
  expect(result.items).toHaveLength(2);
  expect(result.executed).toBe(false);
  get.mockResolvedValue(wire.recovery_response);
  const recovered = await readRevokeBatch(wire.request_key);
  expect(recovered.items.map(item => item.change_status)).toEqual(['approved', 'proposed']);
  expect(recovered.items.map(item => item.change_request_id)).toEqual(result.items.map(item => item.change_request_id));
  expect(get).toHaveBeenCalledExactlyOnceWith(`/network-revoke-batches/${wire.request_key}`);
  expect(post).not.toHaveBeenCalled();
});
