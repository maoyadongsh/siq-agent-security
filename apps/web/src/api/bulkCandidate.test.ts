import { afterEach, expect, it, vi } from 'vitest';
import { assertBulkReadback, confirmCandidateBatch, dismissCandidateBatch, readCandidateBatch, validBulkSelection } from './bulkCandidate';
import type { AgentAsset } from './types';

const candidate: AgentAsset = { id: 'asset_a', name: '候选', role: null, framework: 'hermes', status: 'candidate',
  system_id: null, owner_user_id: null, source_type: null, source_locator: null, updated_at: '2026-09-25T00:00:00Z' };
afterEach(() => vi.unstubAllGlobals());
it.each([[], Array(51).fill(candidate), [candidate, candidate], [{ ...candidate, status: 'confirmed' as const }],
  [{ ...candidate, updated_at: 'invalid' }]].map(rows => ({ rows })))('rejects invalid selection without a write', async ({ rows }) => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  expect(validBulkSelection(rows)).toBe(false);
  await expect(confirmCandidateBatch(rows)).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
it('sends only explicit versions and validates ordered result', async () => {
  const result = { schema_version: 'enterprise-candidate-bulk-confirm-result/v1', items: [{ ...candidate, status: 'confirmed' }] };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(result), { headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('fetch', fetch);
  await confirmCandidateBatch([candidate]);
  expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ schema_version: 'enterprise-candidate-bulk-confirm/v1',
    items: [{ asset_id: 'asset_a', expected_updated_at: candidate.updated_at }] });
  expect(() => assertBulkReadback({ ...result, items: [] }, [candidate])).toThrow();
  expect(() => assertBulkReadback({ ...result, items: [{ ...candidate, status: 'confirmed', id: 'other' }] }, [candidate])).toThrow();
});
it('does not retry an uncertain write; reconciliation only reads', async () => {
  const fetch = vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValueOnce(
    new Response(JSON.stringify({ ...candidate, status: 'confirmed' }), { headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('fetch', fetch);
  await expect(confirmCandidateBatch([candidate])).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect((await readCandidateBatch([candidate]))[0].status).toBe('confirmed');
  expect(fetch.mock.calls.map(call => call[1].method)).toEqual(['POST', 'GET']);
});
it.each(['duplicate', 'out_of_scope', 'not_agent'] as const)('dismisses with explicit bounded reason %s and rejects confirmation readback', async reason => {
  const result = { schema_version: 'enterprise-candidate-bulk-dismiss-result/v1', items: [{ ...candidate, status: 'dismissed' }] };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(result), { headers: { 'content-type': 'application/json' } }));
  vi.stubGlobal('fetch', fetch);
  await dismissCandidateBatch([candidate], reason);
  expect(String(fetch.mock.calls[0][0])).toContain('/candidates/bulk-dismiss');
  expect(JSON.parse(fetch.mock.calls[0][1].body).reason_code).toBe(reason);
  expect(() => assertBulkReadback(result, [candidate], 'confirm')).toThrow();
  expect(() => assertBulkReadback({ ...result, items: [{ ...candidate, status: 'confirmed' }] }, [candidate], 'dismiss')).toThrow();
});
it('does not send invalid dismissal selections', async () => {
  const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
  await expect(dismissCandidateBatch([], 'duplicate')).rejects.toThrow();
  expect(fetch).not.toHaveBeenCalled();
});
