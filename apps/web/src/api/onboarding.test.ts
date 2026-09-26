import { afterEach, describe, expect, it, vi } from 'vitest';
import { controlPlaneURL, edgeCommands, eligibleScanDevices, isOnboardingStatus, onboardingApi, type OnboardingStatus } from './onboarding';
afterEach(() => vi.unstubAllGlobals());
const sample = { schema_version: 'environment-onboarding/v1', environment_id: 'env-1', evaluated_at: '2026-09-23T01:00:00Z', heartbeat_stale_seconds: 90,
  device_count: 1, devices_truncated: false, evidence_count: 0, last_evidence_at: null, scans: [], scans_truncated: false,
  devices: [{ id: 'edge-1', device_identity: 'device-1', version: '0.1', registered_at: '2026-09-23T00:00:00Z', last_seen_at: '2026-09-23T00:59:50Z', status: 'online', connectors: ['hermes'] }] };
describe('enterprise onboarding facts and commands', () => {
  it('offers only online devices with matching capability, never substitutes another identity', () => {
    const progress = sample as OnboardingStatus;
    expect(eligibleScanDevices(undefined, 'hermes')).toEqual([]);
    expect(eligibleScanDevices(progress, 'openclaw')).toEqual([]);
    expect(eligibleScanDevices(progress, 'hermes').map(d => d.device_identity)).toEqual(['device-1']);
    for (const status of ['stale', 'waiting', 'revoked'] as const)
      expect(eligibleScanDevices({ ...progress, devices: [{ ...progress.devices[0], status }] }, 'hermes')).toEqual([]);
    expect(eligibleScanDevices({ ...progress, devices: [{ ...progress.devices[0], connectors: [] }] }, 'hermes')).toEqual([]);
  });
  it.each(['hermes', 'openclaw'] as const)('binds %s submission to selected device and explicit files', async connector => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ task_id: 'task-1' }), { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    expect(await onboardingApi.scan('env-1', connector, 'device-1')).toEqual({ task_id: 'task-1' });
    expect(fetch).toHaveBeenCalledTimes(1);
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body).toEqual({ environment_id: 'env-1', connector, target_device_identity: 'device-1', scope: connector === 'hermes'
      ? { roots: ['~/.hermes/profiles/*'], include: ['config.yaml', 'SOUL.md'] } : { roots: ['~/.openclaw'], include: ['openclaw.json'] } });
  });
  it('requires a target and rejects an unconfirmed submission response', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('{}', { headers: { 'content-type': 'application/json' } }));
    vi.stubGlobal('fetch', fetch);
    await expect(onboardingApi.scan('env-1', 'hermes', '')).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
    await expect(onboardingApi.scan('env-1', 'hermes', 'device-1')).rejects.toThrow('无法核验扫描任务');
  });
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
