import { expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import OnboardingResults from './OnboardingResults';
import type { OnboardingStatus } from '@/api/onboarding';

const base: OnboardingStatus = { schema_version: 'environment-onboarding/v1', environment_id: 'env',
  evaluated_at: '2026-09-25T00:00:00Z', heartbeat_stale_seconds: 300, device_count: 0,
  devices: [], devices_truncated: false, evidence_count: 0, last_evidence_at: null, scans: [], scans_truncated: false };
it('explains remote installation and does not equate empty tasks with no agents', () => {
  const html = renderToStaticMarkup(<OnboardingResults progress={base} />);
  expect(html).toContain('Mac 浏览器');
  expect(html).toContain('不要将此状态理解为没有智能体');
  expect(html).toContain('不表示业务权限已批准');
});
it('preserves incomplete scope and differentiates failed from empty successful discovery', () => {
  const html = renderToStaticMarkup(<OnboardingResults progress={{ ...base, device_count: 101, devices_truncated: true,
    scans_truncated: true, scans: [
      { id: 'a', connector: 'hermes', status: 'failed', created_at: base.evaluated_at, expires_at: base.evaluated_at, device_identity: null, candidate_count: null, evidence_count: null },
      { id: 'b', connector: 'openclaw', status: 'delivered', created_at: base.evaluated_at, expires_at: base.evaluated_at, device_identity: 'device', candidate_count: 0, evidence_count: 0 },
    ] }} />);
  expect(html).toContain('发现失败');
  expect(html).toContain('历史资产保留');
  expect(html).toContain('不据此认定软件未安装');
  expect(html).toContain('在线数量不是环境完整统计');
  expect(html).toContain('不代表完整扫描历史');
});
