import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { DiscoveryOriginDetails } from './DiscoveryOriginPanel';
import type { DiscoveryOrigin } from '@/api/discoveryOrigin';

const origin: DiscoveryOrigin = {
  schema_version: 'enterprise-discovery-origin/v1', asset_id: 'asset', status: 'device_bound',
  environment: { id: 'env', name: '<script>unsafe</script>' }, device: { id: 'edge', identity: 'device', revoked: true },
  reported_framework: 'hermes', assigned_role: null, observations_truncated: true, observations: [],
};
const render = (value: DiscoveryOrigin) => renderToStaticMarkup(<MemoryRouter><DiscoveryOriginDetails origin={value} /></MemoryRouter>);
describe('discovery origin presentation', () => {
  it('escapes source labels and distinguishes historical origin from protection', () => {
    const html = render(origin);
    expect(html).not.toContain('<script>');
    expect(html).toContain('已吊销，仅保留历史来源');
    expect(html).toContain('不代表运行时已绑定');
    expect(html).toContain('不是完整历史');
  });
  it('does not guess a device for legacy or unavailable bindings', () => {
    for (const status of ['legacy_unresolved', 'source_unavailable'] as const) {
      const html = render({ ...origin, status, device: null, environment: null, observations_truncated: false });
      expect(html).not.toContain('采集设备');
      expect(html).not.toContain('<script>');
    }
  });
});
