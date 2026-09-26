import { describe, expect, it } from 'vitest';
import { parseDeploymentSubmission } from './deploymentSubmission';
const value = { schema_version: 'deployment-submission/v1', id: 's1', change_id: 'cr1', deployment_id: 'd1', state: 'unconfirmed', deployment_status: 'pending', preview_digest: 'a'.repeat(64), created_at: '2026-09-23T01:00:00Z' };
describe('durable deployment evidence', () => {
  it('rejects non-string status instead of using array-to-key coercion', () => {
    expect(() => parseDeploymentSubmission({ ...value, deployment_status: ['pending'] }, 'cr1')).toThrow();
  });
  it('accepts an exact pending record without treating it as completed', () => {
    expect(parseDeploymentSubmission(value, 'cr1').state).toBe('unconfirmed');
    expect(parseDeploymentSubmission({ ...value, state: 'recorded', deployment_status: 'sent' }, 'cr1').state).toBe('recorded');
  });
  it('rejects wrong change, ambiguous state, extra payload and invalid identity', () => {
    for (const bad of [null, { ...value, change_id: 'cr2' }, { ...value, state: 'recorded' }, { ...value, deployment_id: '' }, { ...value, raw_policy: {} }, { ...value, created_at: 'yesterday' }, { ...value, preview_digest: '' }]) expect(() => parseDeploymentSubmission(bad, 'cr1')).toThrow();
  });
});
