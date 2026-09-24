import { describe, expect, it } from 'vitest';
import { controlPlaneURL, edgeCommands, isOnboardingStatus } from './onboarding';
const sample = { schema_version: 'environment-onboarding/v1', environment_id: 'env-1', evaluated_at: '2026-09-23T01:00:00Z', heartbeat_stale_seconds: 90,
  device_count: 1, devices_truncated: false, evidence_count: 0, last_evidence_at: null, scans: [], scans_truncated: false,
  devices: [{ id: 'edge-1', device_identity: 'device-1', version: '0.1', registered_at: '2026-09-23T00:00:00Z', last_seen_at: '2026-09-23T00:59:50Z', status: 'online', connectors: ['hermes'] }] };
describe('enterprise onboarding facts and commands', () => {
  it('rejects another environment, false online state and incomplete count claims', () => {
    expect(isOnboardingStatus(sample, 'env-1')).toBe(true);
    expect(isOnboardingStatus(sample, 'env-other')).toBe(false);
    for (const change of [ { device_count: 2 }, { scans: [null] }, { devices: [null] }, { devices: [{ ...sample.devices[0], last_seen_at: null }] },
      { devices: [{ ...sample.devices[0], last_seen_at: '2026-09-23T02:00:00Z' }] }, { devices: [{ ...sample.devices[0], last_seen_at: '2026-09-23T00:00:00Z' }] } ])
      expect(isOnboardingStatus({ ...sample, ...change }, 'env-1')).toBe(false);
  });
  it('accepts local test addresses and rejects credentials or insecure remote endpoints', () => {
    expect(controlPlaneURL('https://security.example.test/')).toBe('https://security.example.test');
    expect(controlPlaneURL('http://127.0.0.1:8600')).toBe('http://127.0.0.1:8600');
    for (const raw of ['https://user:pass@example.test', 'https://example.test?secret=x', 'https://example.test#x', 'http://remote.test', 'javascript:alert(1)', 'https://example.test\n']) expect(controlPlaneURL(raw)).toBeNull();
  });
  it('keeps enrollment material out of commands and rejects non-origin addresses', () => {
    for (const os of ['bash', 'powershell'] as const) {
      const command = edgeCommands('https://security.test/', os)!;
      expect(command.register).toContain('--enrollment-code-stdin');
      expect(command.register).not.toContain('--enrollment-code ');
    }
    expect(edgeCommands("https://security.test/a'b", 'bash')).toBeNull();
    expect(edgeCommands("https://security.test/a'b", 'powershell')).toBeNull();
  });
});
