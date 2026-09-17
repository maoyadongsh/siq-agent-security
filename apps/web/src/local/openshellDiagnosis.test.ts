import { describe, expect, it } from 'vitest';
import { openshellDiagnosisLabel } from './openshellDiagnosis';

describe('OpenShell evidence labels', () => {
  it('never promotes a handshake or readback to isolation', () => {
    expect(openshellDiagnosisLabel({ state: 'handshake_verified' })).toContain('尚未验证');
    expect(openshellDiagnosisLabel({ state: 'policy_readable' })).toContain('尚未验证');
    expect(openshellDiagnosisLabel({ state: 'behavior_verified' })).toBe('保护能力尚未确认');
  });
  it('rejects expired or malformed freshness evidence', () => {
    expect(openshellDiagnosisLabel({ state: 'handshake_verified', expires_at: '2000-01-01' })).toContain('过期');
    expect(openshellDiagnosisLabel({ state: 'policy_readable', expires_at: 'invalid' })).toContain('过期');
  });
});
