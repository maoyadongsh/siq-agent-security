import { describe, expect, it } from 'vitest';
import { executionEvidence, parseChangeExecution, type DeploymentHistory } from './changeExecution';

const deployment: DeploymentHistory = { id: 'dep1', environment_id: 'env1', environment_name: null, binding_id: 'rb1', target: 'sandbox', status: 'effective', created_at: '2026-09-23T00:00:00Z', verification_level: 'config_readback', independent_result: 'not_checked', backend_mutated: null, error_digest: null };
const result = { schema_version: 'change-execution/v1', change_id: 'cr1', change_status: 'effective', evaluated_at: '2026-09-23T01:00:00Z', deployments: [deployment], deployments_truncated: false, expanded: false, audit_access: 'denied', audit_events: [], audit_truncated: false };
describe('exact deployment and audit history', () => {
  it('rejects wrong objects, oversized pages, unexpected payloads and audit leaks', () => {
    expect(parseChangeExecution(result, 'cr1').deployments).toHaveLength(1);
    expect(() => parseChangeExecution(result, 'cr2')).toThrow();
    for (const invalid of [null, { ...result, raw_receipt: {} }, { ...result, evaluated_at: 'unknown' }, { ...result, deployments: Array(21).fill(deployment) }, { ...result, deployments: [{ ...deployment, raw_error: 'secret' }] }, { ...result, audit_truncated: true }, { ...result, deployments: [deployment, deployment] }]) expect(() => parseChangeExecution(invalid, 'cr1')).toThrow();
  });
  it('rejects array or object lookalikes masquerading as enum values', () => {
    const lookalike = (toString: string) => ({ toString: () => toString });
    for (const invalid of [
      { ...result, audit_access: ['denied'] },
      { ...result, audit_access: lookalike('allowed') },
      { ...result, deployments: [{ ...deployment, verification_level: ['behavior_enforced'] }] },
      { ...result, deployments: [{ ...deployment, verification_level: lookalike('none') }] },
      { ...result, deployments: [{ ...deployment, independent_result: ['verified'] }] },
    ]) expect(() => parseChangeExecution(invalid, 'cr1')).toThrow();
    expect(executionEvidence({ ...deployment, verification_level: 'future_level' as never }).tone).not.toBe('ok');
  });
  it('rejects calendar dates that do not exist but Date.parse rolls over', () => {
    for (const invalid of [
      { ...result, evaluated_at: '2026-02-30T00:00:00Z' },
      { ...result, evaluated_at: '2026-02-29T00:00:00Z' },
      { ...result, evaluated_at: '2026-04-31T00:00:00Z' },
      { ...result, deployments: [{ ...deployment, created_at: '2026-06-31T00:00:00Z' }] },
    ]) expect(() => parseChangeExecution(invalid, 'cr1')).toThrow();
    expect(parseChangeExecution({ ...result, evaluated_at: '2024-02-29T00:00:00Z' }, 'cr1').evaluated_at).toBe('2024-02-29T00:00:00Z');
    expect(parseChangeExecution({ ...result, evaluated_at: '2026-09-23T00:00:00.123456Z' }, 'cr1').evaluated_at).toBe('2026-09-23T00:00:00.123456Z');
  });
  it('requires a complete UTC timestamp rather than permissive Date.parse syntax', () => {
    for (const evaluated_at of ['2026-09-23Z', '2026-09-23 00:00:00Z', '2026-09-23T00:00Z']) {
      expect(() => parseChangeExecution({ ...result, evaluated_at }, 'cr1')).toThrow();
    }
  });
  it('never lets old verification hide failure, rollback or negative independent readback', () => {
    expect(executionEvidence(deployment).label).toBe('配置已读回，行为未验证');
    expect(executionEvidence({ ...deployment, status: 'failed' }).tone).toBe('err');
    expect(executionEvidence({ ...deployment, status: 'rolled_back' }).label).toBe('已记录回滚');
    expect(executionEvidence({ ...deployment, independent_result: 'mismatch' }).tone).toBe('err');
    expect(executionEvidence({ ...deployment, independent_result: 'unreachable' }).label).toContain('无法连接');
    expect(executionEvidence({ ...deployment, verification_level: 'behavior_enforced', independent_result: 'no_receipt' }).tone).toBe('warn');
    expect(executionEvidence({ ...deployment, status: 'sent', verification_level: 'behavior_enforced' }).label).toBe('尚无生效验证');
    expect(executionEvidence({ ...deployment, verification_level: 'none', independent_result: 'verified' }).label).toBe('验证证据不足');
  });
});
