import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { isRuntimeCheckActivity, runtimeCheckActivityURL } from './runtimeCheckActivity';
import type { RuntimeCheckResult } from './types';

const sample = JSON.parse(readFileSync(new URL('../../../agentshield/testdata/contracts/local-runtime-check-activity.json', import.meta.url), 'utf8'));
const result = { check_id: sample.check_id, instance_id: sample.instance_id, receipt_ids: ['fixture-501', 'fixture-502'] } as RuntimeCheckResult;

describe('self-check activity reference', () => {
  it('accepts the Go response for the exact check and instance', () => {
    expect(isRuntimeCheckActivity(sample, result)).toBe(true);
    for (const patch of [{ check_id: 'another' }, { instance_id: 'another' }, { receipt_ids: [] }]) {
      expect(isRuntimeCheckActivity(sample, { ...result, ...patch })).toBe(false);
    }
  });
  it('rejects unverified, unbound, partial or malformed references', () => {
    for (const patch of [{ prefix_valid: false }, { history_integrity: 'failed' }, { activity: null }, { snapshot: 'invalid' },
      { activity: { ...sample.activity, binding: null } }, { activity: { ...sample.activity, receipt_count: 1 } },
      { activity: { ...sample.activity, binding: { ...sample.activity.binding, platform: 'openclaw' } } }]) {
      expect(isRuntimeCheckActivity({ ...sample, ...patch }, result)).toBe(false);
    }
  });
  it('preserves the actual activity and full filter scope without deriving task names', () => {
    const url = new URL(runtimeCheckActivityURL(sample), 'http://localhost');
    expect(url.pathname).toBe(`/activities/${sample.activity.activity_id}`);
    for (const field of ['platform', 'agent_id', 'session_id', 'task_id']) {
      expect(url.searchParams.get(field)).toBe(sample.activity.binding[field]);
    }
    expect(url.searchParams.get('snapshot')).toBe(sample.snapshot);
    expect(url.searchParams.get('task_id')).toBe('actual-task-not-derived-from-check-id');
  });
});
