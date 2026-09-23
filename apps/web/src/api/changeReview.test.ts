import { describe, expect, it } from 'vitest';
import { parseChangeReview } from './changeReview';
const sample = {
  schema_version: 'change-review/v1', change_id: 'cr-1', status: 'proposed', policy_name: '研究策略', policy_version: 1,
  enforcement_mode: 'block', approval_policy: 'standard', proposer_id: 'owner', approver_id: null, review_digest: 'a'.repeat(64),
  sections: ['selector', 'filesystem', 'network', 'process', 'model_routing', 'tools', 'tool_policies', 'data_scope_refs', 'secrets', 'resources', 'audit', 'exceptions', 'impact', 'validation', 'previous'].map(key => ({ key, label: key, content: 'null', redacted: false, truncated: false })),
  can_approve: true, can_reject: true, approve_blockers: [], reject_blockers: [],
};
describe('exact change review before decisions', () => {
  it('accepts a complete snapshot but rejects another change or hidden/missing sections', () => {
    expect(parseChangeReview(sample, 'cr-1').can_approve).toBe(true);
    expect(() => parseChangeReview(sample, 'cr-2')).toThrow();
    for (const invalid of [null, { ...sample, unexpected: 'field' }, { ...sample, review_digest: '' }, { ...sample, sections: sample.sections.slice(1) }, { ...sample, sections: sample.sections.map(s => ({ ...s, key: 'network' })) }, { ...sample, sections: sample.sections.map(s => ({ ...s, redacted: true })) }, { ...sample, sections: sample.sections.map(s => ({ ...s, content: 'x'.repeat(6001) })) }]) expect(() => parseChangeReview(invalid, 'cr-1')).toThrow();
  });
  it('fails closed on inconsistent permissions and processed status', () => {
    for (const invalid of [{ ...sample, can_approve: 'true' }, { ...sample, approve_blockers: ['own_proposal'] }, { ...sample, approve_blockers: ['unknown'], can_approve: false }, { ...sample, status: 'approved' }]) expect(() => parseChangeReview(invalid, 'cr-1')).toThrow();
    expect(parseChangeReview({ ...sample, can_approve: false, approve_blockers: ['own_proposal'] }, 'cr-1').can_approve).toBe(false);
  });
});
