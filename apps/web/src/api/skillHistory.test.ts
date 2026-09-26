import { afterEach, expect, it, vi } from 'vitest';
import { getSkillHistory, isSkillHistoryPage } from './skillHistory';
import type { SkillObservation } from './skillInventory';

const observation: SkillObservation = {
  observation_id: 'smo_b', manifest_sha256: 'a'.repeat(64), batch_digest: 'b'.repeat(64),
  parser_version: 'enterprise-skill-manifest/v1', parse_status: 'parsed', name: 'fixture',
  allowed_tools_present: true, declared_tools: ['read_file'], observed_at: '2026-09-25T00:00:00Z',
};
const earlier = { ...observation, observation_id: 'smo_a' };
const page = { schema_version: 'enterprise-skill-history/v1', installation_id: 'ski_a',
  items: [observation, earlier], next_cursor: 'smo_a' };
afterEach(() => vi.unstubAllGlobals());
it('accepts descending history, ties and empty history without inventing permissions', () => {
  expect(isSkillHistoryPage(page, 'ski_a')).toBe(true);
  expect(isSkillHistoryPage({ ...page, items: [], next_cursor: null }, 'ski_a')).toBe(true);
  expect(isSkillHistoryPage({ ...page, items: [earlier] }, 'ski_a', observation)).toBe(true);
});
it.each([
  { schema_version: 'unknown' }, { installation_id: 'ski_other' }, { items: Array(201).fill(observation) },
  { items: [earlier, observation] }, { items: [observation, observation] }, { next_cursor: 'smo_other' },
  { items: [{ ...observation, observed_at: 'bad' }] }, { items: [{ ...observation, declared_tools: ['a', 'a'] }] },
  { items: [{ ...observation, parse_status: 'unsupported' }] }, { items: [{ ...observation, observation_id: '../x' }] },
])('rejects malformed, mismatched or unordered history %j', patch => {
  expect(isSkillHistoryPage({ ...page, ...patch }, 'ski_a')).toBe(false);
});
it('rejects a repeated or newer page across the cursor boundary', () => {
  expect(isSkillHistoryPage(page, 'ski_a', observation)).toBe(false);
  expect(isSkillHistoryPage(page, 'ski_a', earlier)).toBe(false);
});
it('uses a read-only encoded endpoint and checks the response installation', async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(page), {
    headers: { 'content-type': 'application/json' },
  })));
  vi.stubGlobal('fetch', fetch);
  await expect(getSkillHistory('ski_a')).resolves.toEqual(page);
  await expect(getSkillHistory('other/id')).rejects.toThrow('无法核验');
  expect(String(fetch.mock.calls[1][0])).toContain('other%2Fid/observations');
  await expect(getSkillHistory('ski_a', observation)).rejects.toThrow('无法核验');
  expect(String(fetch.mock.calls[2][0])).toContain('cursor=smo_b');
});
