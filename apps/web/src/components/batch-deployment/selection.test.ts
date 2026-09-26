import { describe, expect, it } from 'vitest';
import { addBatchSelection, batchRequestKey } from './selection';
const item = { change_request_id: 'c1', environment_id: 'e1', binding_id: 'b1' };
describe('explicit per-change batch selection', () => {
  it('generates RFC UUID v4 using secure random bytes without requiring randomUUID', () => {
    const key = batchRequestKey();
    expect(key).toMatch(/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    expect(batchRequestKey()).not.toBe(key);
  });
  it('preserves prior target assignments without mutating the selection', () => {
    const source = [item];
    const result = addBatchSelection(source, { ...item, change_request_id: 'c2', binding_id: 'b2' });
    expect(result).toHaveLength(2); expect(source).toEqual([item]); expect(result[0]).toEqual(item);
  });
  it('rejects duplicate change or target binding', () => {
    expect(() => addBatchSelection([item], { ...item, binding_id: 'b2' })).toThrow();
    expect(() => addBatchSelection([item], { ...item, change_request_id: 'c2' })).toThrow();
  });
  it('never silently truncates beyond 20', () => {
    const source = Array.from({ length: 20 }, (_, n) => ({ ...item, change_request_id: `c${n}`, binding_id: `b${n}` }));
    expect(() => addBatchSelection(source, { ...item, change_request_id: 'c21', binding_id: 'b21' })).toThrow('20');
    expect(source).toHaveLength(20);
  });
});
