import { describe, expect, it } from 'vitest';
import { parseDeploymentPreview } from './deploymentPreview';
const selected = { change_request_id: 'cr1', environment_id: 'env1', binding_id: 'rb1' };
const value = { schema_version: 'deployment-preview/v1', change_id: 'cr1', policy_id: 'p1', policy_name: '研究策略', policy_version: 1, enforcement_mode: 'block', environment_id: 'env1', environment_name: '研究环境', binding_id: 'rb1', target: 'sandbox1', backend: 'fake', action: 'development_task', base_revision: null, preview_digest: 'a'.repeat(64) };
describe('deployment preview target binding', () => {
  it('rejects an array masquerading as an enforcement mode', () => {
    expect(() => parseDeploymentPreview({ ...value, enforcement_mode: ['block'] }, selected)).toThrow();
  });
  it('rejects object swaps and inconsistent backend/action evidence', () => {
    expect(parseDeploymentPreview(value, selected).target).toBe('sandbox1');
    for (const invalid of [null, { ...value, binding_id: 'other' }, { ...value, environment_id: 'other' }, { ...value, change_id: 'other' }, { ...value, action: 'dynamic_update' }, { ...value, backend: 'openshell-cli' }, { ...value, preview_digest: '' }, { ...value, raw_policy: {} }]) expect(() => parseDeploymentPreview(invalid, selected)).toThrow();
  });
  it('accepts a scoped live revision but never fabricates it for OpenShell', () => {
    expect(parseDeploymentPreview({ ...value, backend: 'openshell-cli', action: 'dynamic_update', base_revision: '4' }, selected).base_revision).toBe('4');
    expect(() => parseDeploymentPreview({ ...value, backend: 'openshell-cli', action: 'dynamic_update' }, selected)).toThrow();
  });
});
