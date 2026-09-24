import type { DiscoveryStatus } from './types';

type DiscoveryClient = {
  discoveryStatus(): Promise<DiscoveryStatus>;
  discoveryScan(input: Record<string, never>): Promise<DiscoveryStatus>;
};

// Component-owned single flight also covers React's StrictMode effect replay.
// Keep neither credentials nor completed results here; every revisit reads the server.
export function createDiscoveryStarter(client: DiscoveryClient) {
  let pending: Promise<DiscoveryStatus> | undefined;
  return (): Promise<DiscoveryStatus> => {
    if (pending) return pending;
    pending = (async () => {
      const status = await client.discoveryStatus();
      if (status.run.state !== 'idle') return status;
      try {
        return await client.discoveryScan({});
      } catch (error) {
        // Another tab may have started the same scan. Observe it, never retry POST.
        if (error instanceof Error && 'status' in error && error.status === 409) {
          return client.discoveryStatus();
        }
        throw error;
      }
    })().finally(() => { pending = undefined; });
    return pending;
  };
}
