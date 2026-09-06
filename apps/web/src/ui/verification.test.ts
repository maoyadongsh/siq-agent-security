import { describe, expect, it } from 'vitest';
import {
  classifyDeploymentVerification,
  permissionStateLabel,
} from './verification';

describe('DEV13-C verification display', () => {
  it('treats missing verification as not enforced even if effective', () => {
    const v = classifyDeploymentVerification('effective', null);
    expect(v.kind).toBe('none');
    expect(v.label).toBe('未验证');
    expect(v.label).not.toMatch(/阻断/);
  });

  it('labels config readback without claiming behavior enforcement', () => {
    const v = classifyDeploymentVerification('effective', {
      level: 'readback_verified',
      method: 'config_readback',
    });
    expect(v.kind).toBe('config_readback');
    expect(v.label).toBe('配置已读回');
    expect(v.label).not.toMatch(/阻断已验证/);
  });

  it('only claims behavior when enforcement_verified', () => {
    const v = classifyDeploymentVerification('effective', {
      level: 'enforcement_verified',
      method: 'behavior_fixture',
      verified_at: '2026-09-06T00:00:00Z',
    });
    expect(v.kind).toBe('behavior_enforced');
    expect(v.label).toBe('阻断已验证');
  });

  it('marks failed and stale', () => {
    expect(classifyDeploymentVerification('failed', { level: 'failed' }).kind).toBe('failed');
    expect(classifyDeploymentVerification('effective', { level: 'readback_verified', stale: true }).kind).toBe(
      'stale',
    );
  });

  it('maps permission five-states', () => {
    expect(permissionStateLabel('declared')).toBe('声明');
    expect(permissionStateLabel('inferred')).toBe('推断');
    expect(permissionStateLabel('observed')).toBe('观测');
    expect(permissionStateLabel('effective')).toBe('生效');
    expect(permissionStateLabel('unknown')).toBe('未知');
  });
});
