import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { activityQueryParams, isActivityQueryPage, localDateTime, readActivityFilters } from './activityQuery';
const sample = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-task-activity-query.json', import.meta.url), 'utf8'));

describe('activity query contract', () => {
  it('accepts the Go summary without treating observations as decisions', () => {
    expect(isActivityQueryPage(sample, 'tasks', 0, sample.filters)).toBe(true);
    expect(sample.items[0].decisions.allow).toBe(1);
    expect(sample.items[0].receipt_count).toBe(4);
  });
  it('rejects scope changes, malformed dates, counts and order', () => {
    expect(isActivityQueryPage(sample, 'tasks', 0, { ...sample.filters, action: 'allow' })).toBe(false);
    for (const item of [{ ...sample.items[0], last_recorded_at: 'bad' },
      { ...sample.items[0], decisions: { ...sample.items[0].decisions, allow: -1 } },
      { ...sample.items[0], decisions: { ...sample.items[0].decisions, allow: 10 } }]) {
      expect(isActivityQueryPage({ ...sample, items: [item] }, 'tasks', 0, sample.filters)).toBe(false);
    }
    expect(isActivityQueryPage({ ...sample, prefix_valid: false }, 'tasks', 0, sample.filters)).toBe(false);
  });
  it('keeps time boundaries distinct from the originating list offset', () => {
    const params = activityQueryParams('tasks', sample.filters, { list_offset: '50' });
    expect(params.get('from')).toBe(sample.filters.from);
    expect(params.get('list_offset')).toBe('50');
    expect(readActivityFilters(params)).toEqual(sample.filters);
    expect(new Date(localDateTime(sample.filters.from)).toISOString()).toBe('2026-09-23T02:00:00.000Z');
  });
});
