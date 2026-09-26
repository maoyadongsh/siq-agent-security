import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ChangeReview } from '@/api/changeReview';
import type { DeploymentPreview } from '@/api/deploymentPreview';
import { readBatchItemReview } from './review';
const read = vi.hoisted(() => vi.fn());
vi.mock('@/api/changeReview', () => ({ readChangeReview: read }));
const item = { change_id: 'c1', policy_name: 'Policy', policy_version: 2, enforcement_mode: 'block' } as DeploymentPreview;
const fixture = () => ({ change_id: 'c1', policy_name: 'Policy', policy_version: 2, enforcement_mode: 'block', status: 'approved', sections: [{ key: 'impact', redacted: false, truncated: false, content: '{}' }] }) as ChangeReview;
beforeEach(() => { read.mockReset(); });
describe('batch approved content inspection (not execution authority)', () => {
  it('reads the exact change without invoking approval or execution', async () => {
    const review = fixture(); read.mockResolvedValue(review);
    expect(await readBatchItemReview(item)).toBe(review);
    expect(read).toHaveBeenCalledExactlyOnceWith('c1');
  });
  it.each([{ change_id: 'other' }, { policy_version: 3 }, { policy_name: 'Other' }, { enforcement_mode: 'warn' }, { status: 'proposed' }, { status: 'effective' }])('rejects changed content/state %j', async patch => {
    read.mockResolvedValue({ ...fixture(), ...patch });
    await expect(readBatchItemReview(item)).rejects.toThrow('不一致');
  });
  it.each(['redacted', 'truncated'])('rejects incomplete %s content', async key => {
    const review = fixture(); Object.assign(review.sections[0], { [key]: true }); read.mockResolvedValue(review);
    await expect(readBatchItemReview(item)).rejects.toThrow('隐藏或截断');
  });
  it('does not turn a denied read into an empty successful review', async () => {
    read.mockRejectedValue(new Error('denied'));
    await expect(readBatchItemReview(item)).rejects.toThrow('denied');
  });
  it('retains emergency approval semantics without inventing a standard approval', async () => {
    read.mockResolvedValue({ ...fixture(), status: 'emergency_applied', approval_policy: 'break_glass' });
    expect((await readBatchItemReview(item)).approval_policy).toBe('break_glass');
  });
});
