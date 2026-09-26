import { describe, expect, it } from 'vitest';
import { canBatchRevoke, validBatchPlan, validBatchResult, type GrantBatchPlan } from './grantBatch';
import type { Grant } from './types';

const targets = [{ grant_id: 'g1', expected_revision: 2 }];
const plan: GrantBatchPlan = {
  schema_version: 'grant-batch-revoke-plan/v1', signing_schema: 'local_canonical/v1', signature: 'a'.repeat(128),
  batch_id: `gb-${'b'.repeat(64)}`, actor_id: 'human', action: 'revoke', expires_at: new Date(Date.now() + 240000).toISOString(),
  items: [{ ...targets[0], subject_id: 'role', platform: 'hermes', status: 'effective' }],
};
describe('batch revoke fail-closed response handling', () => {
  it('requires the exact reviewed selection, revision and operator', () => {
    expect(validBatchPlan(plan, targets, 'human')).toBe(true);
    for (const bad of [null, {}, { ...plan, action: 'approve' }, { ...plan, actor_id: 'agent' },
      { ...plan, expires_at: '2000-01-01' }, { ...plan, items: [] },
      { ...plan, items: [{ ...plan.items[0], grant_id: 'another' }] },
      { ...plan, items: [{ ...plan.items[0], expected_revision: 3 }] },
      { ...plan, items: [{ ...plan.items[0], status: 'revoked' }] },
    ]) expect(validBatchPlan(bad, targets, 'human')).toBe(false);
  });
  it('never converts missing, mismatched or unknown partial results into success', () => {
    const result = { schema_version: 'grant-batch-revoke-result/v1', batch_id: plan.batch_id,
      items: [{ grant_id: 'g1', status: 'revoked', state_revision: 3 }] };
    expect(validBatchResult(result, plan)).toBe(true);
    expect(validBatchResult({ ...result, items: [{ grant_id: 'g1', status: 'unavailable' }] }, plan)).toBe(true);
    for (const bad of [{}, { ...result, batch_id: 'another' }, { ...result, items: [] },
      { ...result, items: [{ grant_id: 'g1', status: 'revoked' }] },
      { ...result, items: [{ grant_id: 'g2', status: 'revoked', state_revision: 3 }] },
      { ...result, items: [{ grant_id: 'g1', status: 'allow', state_revision: 3 }] },
    ]) expect(validBatchResult(bad, plan)).toBe(false);
  });
  it('does not select terminal grants or grants without a CAS revision', () => {
    expect(canBatchRevoke({ status: 'approved', state_revision: 0 } as Grant)).toBe(true);
    for (const g of [{ status: 'revoked', state_revision: 2 }, { status: 'effective' }, { status: 'approved', state_revision: -1 }]) {
      expect(canBatchRevoke(g as Grant)).toBe(false);
    }
  });
});
