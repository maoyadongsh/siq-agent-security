import { describe, expect, it } from 'vitest';
import { grantExpiryLabel, verifyAdapterReadback, verifyAdapterResult, verifyDeployedGrant } from './managedReadback';
import type { AdapterInstances, AdapterPlan, Grant } from './types';

describe('managed connection readback', () => {
  const plan = { platform: 'workbuddy', action: 'install', instance_id: 'hi-example' } as AdapterPlan;
  const catalog = (state: string, status = 'pass') => ({ instances: [{ instance_id: plan.instance_id,
    diagnosis: { configuration_state: state, runtime_state: 'unverified', checks: [{ code: 'config', status }] } }] }) as AdapterInstances;
  it('requires the actual operation and same instance diagnosis', () => {
    expect(() => verifyAdapterResult(plan, { platform: 'workbuddy', action: 'install' })).not.toThrow();
    expect(() => verifyAdapterResult(plan, { platform: 'workbuddy', action: 'skipped' })).toThrow();
    expect(() => verifyAdapterResult(plan, { platform: 'hermes', action: 'install' })).toThrow();
    expect(() => verifyAdapterReadback(plan, catalog('ready'))).not.toThrow();
    expect(() => verifyAdapterReadback(plan, catalog('ready', 'fail'))).toThrow();
    for (const state of ['not_installed', 'incomplete', 'unsupported']) expect(() => verifyAdapterReadback(plan, catalog(state))).toThrow();
    expect(() => verifyAdapterReadback(plan, { instances: [] } as unknown as AdapterInstances)).toThrow();
    const readback = catalog('ready');
    verifyAdapterReadback(plan, readback);
    expect(readback.instances[0].diagnosis.runtime_state).toBe('unverified');
  });
  it('does not confirm approval alone, revoked grants or a concurrent revision', () => {
    const applied = { grant_id: 'g-1', status: 'deployed', state_revision: 3 } as Grant;
    expect(() => verifyDeployedGrant(applied, applied)).not.toThrow();
    for (const status of ['pending_approval', 'approved', 'revoked', 'expired']) expect(() => verifyDeployedGrant(applied, { ...applied, status })).toThrow();
    expect(() => verifyDeployedGrant(applied, { ...applied, state_revision: 4 })).toThrow();
    expect(() => verifyDeployedGrant(applied, { ...applied, grant_id: 'g-2' })).toThrow();
  });
  it('keeps historical hook failure separate from a successful configuration repair', () => {
    for (const platform of ['hermes', 'openclaw', 'workbuddy']) {
      const readback = catalog('ready');
      readback.instances[0].diagnosis.checks.push({ code: 'hook_load', status: 'fail', message: 'previous self-check failed' });
      expect(() => verifyAdapterReadback({ ...plan, platform }, readback)).not.toThrow();
      expect(readback.instances[0].diagnosis.checks[1].status).toBe('fail');
      expect(readback.instances[0].diagnosis.runtime_state).toBe('unverified');
      readback.instances[0].diagnosis.checks.push({ code: 'instance_authority', status: 'fail', message: 'revoked' });
      expect(() => verifyAdapterReadback({ ...plan, platform }, readback)).toThrow();
    }
  });
  it('preserves unknown versus explicit unlimited grant lifetime', () => {
    expect(grantExpiryLabel(undefined)).toContain('未知');
    expect(grantExpiryLabel('invalid')).toContain('未知');
    expect(grantExpiryLabel(null)).toBe('未设置到期时间');
    expect(grantExpiryLabel('2026-09-28T00:00:00Z')).not.toContain('未知');
  });
});
