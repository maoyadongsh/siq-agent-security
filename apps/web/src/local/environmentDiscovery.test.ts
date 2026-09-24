import { describe, expect, it, vi } from 'vitest';
import { createDiscoveryStarter } from './environmentDiscovery';
import type { DiscoveryStatus } from './types';

const status = (state: DiscoveryStatus['run']['state']): DiscoveryStatus => ({
  schema_version: 'local-discovery/v1', roots: [], platform_changes: false,
  run: { state, asset_count: 0, skill_count: 0, issue_count: 0 },
});

describe('automatic local discovery', () => {
  it('starts default discovery once for concurrent mounts without asking for a path', async () => {
    const client = { discoveryStatus: vi.fn().mockResolvedValue(status('idle')),
      discoveryScan: vi.fn().mockResolvedValue(status('running')) };
    const start = createDiscoveryStarter(client);
    const results = await Promise.all([start(), start(), start()]);
    expect(client.discoveryStatus).toHaveBeenCalledTimes(1);
    expect(client.discoveryScan).toHaveBeenCalledExactlyOnceWith({});
    expect(results.every((result) => result.run.state === 'running')).toBe(true);
  });
  it.each(['running', 'succeeded', 'partial', 'failed'] as const)('does not restart a %s scan', async (state) => {
    const client = { discoveryStatus: vi.fn().mockResolvedValue(status(state)), discoveryScan: vi.fn() };
    expect((await createDiscoveryStarter(client)()).run.state).toBe(state);
    expect(client.discoveryScan).not.toHaveBeenCalled();
  });
  it('joins a scan started by another tab, without a second POST', async () => {
    const client = { discoveryStatus: vi.fn().mockResolvedValueOnce(status('idle')).mockResolvedValue(status('running')),
      discoveryScan: vi.fn().mockRejectedValue(Object.assign(new Error('busy'), { status: 409 })) };
    expect((await createDiscoveryStarter(client)()).run.state).toBe('running');
    expect(client.discoveryScan).toHaveBeenCalledTimes(1);
  });
  it('does not silently retry errors, but allows an explicit later attempt', async () => {
    const client = { discoveryStatus: vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(status('idle')),
      discoveryScan: vi.fn().mockResolvedValue(status('running')) };
    const start = createDiscoveryStarter(client);
    await expect(start()).rejects.toThrow('offline');
    expect(client.discoveryScan).not.toHaveBeenCalled();
    expect((await start()).run.state).toBe('running');
  });
});
