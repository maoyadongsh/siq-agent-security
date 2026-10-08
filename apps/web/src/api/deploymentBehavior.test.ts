import { describe, expect, it, vi } from 'vitest';
import { assessmentLabel, collectBehavior, parseBehaviorAssessment, parseBehaviorOperation, parseBehaviorProfiles } from './deploymentBehavior';
import { post } from './client';
vi.mock('./client', () => ({ get: vi.fn(), post: vi.fn(), requestWithHeaders: vi.fn() }));

const scope = { target: 'sandbox', policy_revision: '2', policy_digest: 'a'.repeat(64), transport: 'http_connect', endpoint: '127.0.0.1:9000', allow_path: '/opt/allow', deny_path: '/opt/deny', attempts: 3 };
const raw = { schema_version: 'deployment-behavior-operation/v1', deployment_id: 'dep', verification_id: 'opv-' + 'a'.repeat(32), profile_id: 'test', state: 'accepted', reason_code: 'accepted', issued_at: '2026-10-08T00:00:00Z', expires_at: '2026-10-08T00:05:00Z', observed_at: '2026-10-08T00:00:03Z', time_window: 'within', current_enforcement_verified: false, observation_count: 12, scope };
const operation = () => parseBehaviorOperation(raw, 'dep');
const assessment = { schema_version: 'deployment-behavior-assessment/v1', deployment_id: 'dep', verification_id: raw.verification_id, evaluated_at: '2026-10-08T00:00:04Z', valid_until: raw.expires_at, state: 'verified', level: 'enforcement_verified', current_enforcement_verified: true, reason_code: 'behavior_current_scope_verified', scope };
const profile = { profile_id: 'test', profile_sha256: 'b'.repeat(64), issued_at: raw.issued_at, expires_at: raw.expires_at, timeout_ms: 1000, scope };
const catalog = { schema_version: 'deployment-behavior-profiles/v1', deployment_id: 'dep', profiles: [profile] };

describe('behavior contract and presentation', () => {
  it('requires bound history, assessment and expiry before showing positive scope', () => {
    const op = operation();
    const result = parseBehaviorAssessment(assessment, op);
    expect(assessmentLabel(result, Date.parse('2026-10-08T00:01:00Z'))).toBe('核验时，该范围行为已验证');
    expect(assessmentLabel(result, Date.parse(raw.expires_at))).toBe('核验证据已过期');
    expect(assessmentLabel(null, Date.now())).toBe('尚未核验当前目标');
  });
  it.each([
    { deployment_id: 'different' }, { verification_id: 'opv-' + 'b'.repeat(32) }, { level: 'unverified' },
    { current_enforcement_verified: false }, { valid_until: '2026-10-08T00:06:00Z' },
    { evaluated_at: '2026-10-08T00:00:00Z' }, { valid_until: null }, { state: 'changed' },
    { scope: { ...scope, policy_digest: 'c'.repeat(64) } }, { scope: { ...scope, target: 'other' } },
  ])('rejects inconsistent positive assessment %j', patch => {
    expect(() => parseBehaviorAssessment({ ...assessment, ...patch }, operation())).toThrow();
  });
  it.each([
    { current_enforcement_verified: true }, { observed_at: null }, { observation_count: 11 },
    { expires_at: '2026-02-30T00:00:00Z' }, { scope: { ...scope, endpoint: '999.0.0.1:443' } },
    { scope: { ...scope, endpoint: '127.0.0.1:99999' } }, { scope: { ...scope, allow_path: '/opt/../allow' } },
  ])('rejects misleading or malformed historical evidence %j', patch => {
    expect(() => parseBehaviorOperation({ ...raw, ...patch }, 'dep')).toThrow();
  });
  it('unknown is not promoted and incomplete records retain null observation time', () => {
    const op = parseBehaviorOperation({ ...raw, state: 'unknown', observed_at: null, observation_count: 0 }, 'dep');
    expect(() => parseBehaviorAssessment(assessment, op)).toThrow();
    const failed = parseBehaviorAssessment({ ...assessment, state: 'unavailable', valid_until: null, level: 'unverified', current_enforcement_verified: false }, op);
    expect(assessmentLabel(failed, Date.now())).toBe('暂时无法核验当前目标');
  });
  it('rejects cross-deployment profiles and duplicate template IDs', () => {
    expect(parseBehaviorProfiles(catalog, 'dep')).toHaveLength(1);
    expect(() => parseBehaviorProfiles(catalog, 'other')).toThrow();
    expect(() => parseBehaviorProfiles({ ...catalog, profiles: [profile, profile] }, 'dep')).toThrow();
  });
  it('submits only the displayed profile hash with v2 and preserves caller request ID', async () => {
    vi.mocked(post).mockResolvedValueOnce(raw);
    await collectBehavior('dep', parseBehaviorProfiles(catalog, 'dep')[0], raw.verification_id);
    expect(post).toHaveBeenCalledWith('/deployments/dep/behavior-verifications', {
      schema_version: 'deployment-behavior-start/v2', profile_id: 'test', profile_sha256: 'b'.repeat(64), verification_id: raw.verification_id,
    }, { timeoutMs: 320000 });
  });
});
