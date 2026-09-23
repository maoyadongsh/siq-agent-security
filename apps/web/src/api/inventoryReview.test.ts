import { describe, expect, it } from 'vitest';
import { assertReviewReadback, assetStatusLabel, pendingCandidate } from './inventoryReview';
import type { AgentAsset } from './types';
const asset: AgentAsset = { id: 'asset-1', name: '研究助手', status: 'confirmed', framework: 'hermes', role: '研究分析', owner_user_id: null, system_id: null, source_type: null, source_locator: null, updated_at: '2026-09-23T00:00:00Z' };
describe('candidate review verified readback', () => {
  it('requires exact object, resulting state and submitted business role', () => {
    expect(assertReviewReadback(asset, 'asset-1', 'confirm', '研究分析')).toBe(asset);
    expect(() => assertReviewReadback(asset, 'other', 'confirm', '研究分析')).toThrow();
    expect(() => assertReviewReadback(asset, 'asset-1', 'dismiss', '')).toThrow();
    expect(() => assertReviewReadback(asset, 'asset-1', 'confirm', '审查')).toThrow();
    expect(() => assertReviewReadback({ ...asset, status: 'candidate' }, 'asset-1', 'confirm', '')).toThrow();
  });
  it('distinguishes confirmation from management and pending candidates', () => {
    expect(assetStatusLabel('confirmed')).toBe('已确认');
    expect(assetStatusLabel('managed')).toBe('已纳管');
    expect(pendingCandidate(asset)).toBe(false);
    expect(pendingCandidate({ ...asset, status: 'needs_review' })).toBe(true);
    expect(assetStatusLabel('unexpected')).toBe('状态待核实');
  });
});
