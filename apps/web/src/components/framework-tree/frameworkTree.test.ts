import { expect, it } from 'vitest';
import type { FrameworkRoleInventoryItem } from '@/api/frameworkRoleInventory';
import { groupFrameworkRoles } from './frameworkTree';

const digest = (char: string) => char.repeat(64);

function sourceView(assetId: string, overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 'enterprise-framework-source-view/v1' as const, asset_id: assetId,
    status: 'historical_reported_source' as const, runtime_status: 'unverified' as const,
    skill_relationship_status: 'unresolved' as const, effective_permissions: null,
    source: {
      framework: 'openclaw' as const, instance_key: digest('a'), environment_id: 'env-one',
      device_id: 'edge-one', device_revoked: false, config_sha256: digest('b'),
      evidence_id: 'ev:one', observation_id: 'evo-one', observed_at: '2026-09-25T12:00:00Z',
    },
    ...overrides,
  };
}

function role(assetId: string, overrides: Record<string, unknown> = {}): FrameworkRoleInventoryItem {
  return {
    asset_id: assetId, name: `角色 ${assetId}`, reported_framework: 'openclaw',
    asset_status: 'confirmed', framework_source: sourceView(assetId), ...overrides,
  } as FrameworkRoleInventoryItem;
}

it('groups multiple roles of the same instance into one group', () => {
  const grouped = groupFrameworkRoles([role('agt_a'), role('agt_b')]);
  expect(grouped.environments).toHaveLength(1);
  expect(grouped.environments[0].devices).toHaveLength(1);
  expect(grouped.environments[0].devices[0].instances).toHaveLength(1);
  expect(grouped.environments[0].devices[0].instances[0].roles.map(r => r.item.asset_id)).toEqual(['agt_a', 'agt_b']);
});

it('keeps Hermes and OpenClaw separate even with the same instance digest', () => {
  const hermes = role('agt_b');
  hermes.reported_framework = 'hermes';
  hermes.framework_source.schema_version = 'enterprise-framework-source-view/v2';
  hermes.framework_source.source!.framework = 'hermes';
  const grouped = groupFrameworkRoles([role('agt_a'), hermes]);
  const instances = grouped.environments[0].devices[0].instances;
  expect(instances).toHaveLength(2);
  expect(new Set(instances.map(instance => instance.framework))).toEqual(new Set(['openclaw', 'hermes']));
  expect(grouped.sourceUnavailable).toHaveLength(0);
});

it.each([false, true])('keeps ambiguous environment/device concatenations separate (different instance=%s)', differentInstance => {
  const make = (id: string, environment: string, device: string, instance: string) => role(id, {
    framework_source: sourceView(id, { source: { ...sourceView(id).source,
      environment_id: environment, device_id: device, instance_key: digest(instance) } }),
  });
  const grouped = groupFrameworkRoles([
    make('agt_a', 'env-a', 'bc', 'a'),
    make('agt_b', 'env-ab', 'c', differentInstance ? 'b' : 'a'),
  ]);
  expect(grouped.environments.map(e => [e.environmentId, e.devices.map(d => d.deviceId)])).toEqual([
    ['env-a', ['bc']], ['env-ab', ['c']],
  ]);
  expect(grouped.environments.flatMap(e => e.devices.flatMap(d => d.instances))).toHaveLength(2);
});

it('merges the same instance across pages into one group', () => {
  const page1 = [role('agt_a'), role('agt_b')];
  const page2 = [role('agt_c', {
    framework_source: sourceView('agt_c', {
      source: { ...sourceView('agt_c').source, config_sha256: digest('c') },
    }),
  })];
  const grouped = groupFrameworkRoles([...page1, ...page2]);
  expect(grouped.environments[0].devices[0].instances).toHaveLength(1);
  expect(grouped.environments[0].devices[0].instances[0].roles).toHaveLength(3);
});

it('never merges same instance_key across devices or environments', () => {
  const otherDevice = role('agt_b', {
    name: '角色 agt_a', // 同名同摘要，仍属另一设备
    framework_source: sourceView('agt_b', {
      source: { ...sourceView('agt_b').source, device_id: 'edge-two' },
    }),
  });
  const otherEnv = role('agt_c', {
    framework_source: sourceView('agt_c', {
      source: { ...sourceView('agt_c').source, environment_id: 'env-two' },
    }),
  });
  const grouped = groupFrameworkRoles([role('agt_a'), otherDevice, otherEnv]);
  expect(grouped.environments).toHaveLength(2);
  const allInstances = grouped.environments.flatMap(env => env.devices.flatMap(device => device.instances));
  expect(allInstances).toHaveLength(3);
  expect(new Set(allInstances.map(group => group.key)).size).toBe(3);
});

it('does not deduplicate roles with the same name', () => {
  const grouped = groupFrameworkRoles([
    role('agt_a', { name: 'web-scraper' }),
    role('agt_b', { name: 'web-scraper' }),
  ]);
  const roles = grouped.environments[0].devices[0].instances[0].roles;
  expect(roles.map(r => r.item.asset_id)).toEqual(['agt_a', 'agt_b']);
});

it('keeps no_recorded_source and source_unavailable in separate buckets', () => {
  const grouped = groupFrameworkRoles([
    role('agt_a'),
    role('agt_b', { framework_source: sourceView('agt_b', { status: 'no_recorded_source', source: null }) }),
    role('agt_c', { framework_source: sourceView('agt_c', { status: 'source_unavailable', source: null }) }),
  ]);
  expect(grouped.environments[0].devices[0].instances[0].roles).toHaveLength(1);
  expect(grouped.noRecordedSource.map(r => r.item.asset_id)).toEqual(['agt_b']);
  expect(grouped.sourceUnavailable.map(r => r.item.asset_id)).toEqual(['agt_c']);
});

it('drops an identical duplicate asset without conflict', () => {
  const grouped = groupFrameworkRoles([role('agt_a'), role('agt_a')]);
  expect(grouped.environments[0].devices[0].instances[0].roles).toHaveLength(1);
  expect(grouped.conflictCount).toBe(0);
});

it('flags conflicting duplicates instead of silently picking one as verified', () => {
  const conflicting = role('agt_a', { name: '被改动的名称', asset_status: 'stale' });
  const grouped = groupFrameworkRoles([role('agt_a'), conflicting]);
  const roles = grouped.environments[0].devices[0].instances[0].roles;
  expect(roles).toHaveLength(1);
  expect(roles[0].item.name).toBe('角色 agt_a'); // 保留首条
  expect(roles[0].conflict).toBe(true);
  expect(grouped.conflictCount).toBe(1);
});

it('marks the device revoked when any page reports the credential revoked', () => {
  const revoked = role('agt_b', {
    framework_source: sourceView('agt_b', {
      source: { ...sourceView('agt_b').source, device_revoked: true },
    }),
  });
  const grouped = groupFrameworkRoles([role('agt_a'), revoked]);
  expect(grouped.environments[0].devices[0].deviceRevoked).toBe(true);
  expect(grouped.environments[0].devices[0].instances[0].deviceRevoked).toBe(true);
});

it('produces deterministic ordering regardless of arrival order', () => {
  const a = role('agt_a', {
    framework_source: sourceView('agt_a', {
      source: { ...sourceView('agt_a').source, environment_id: 'env-b', instance_key: digest('9') },
    }),
  });
  const b = role('agt_b'); // env-one / digest('a')
  const forward = groupFrameworkRoles([a, b]);
  const reverse = groupFrameworkRoles([b, a]);
  const order = (g: ReturnType<typeof groupFrameworkRoles>) =>
    g.environments.flatMap(e => e.devices.flatMap(d => d.instances.map(i => i.instanceKey)));
  expect(order(forward)).toEqual(order(reverse));
  expect(order(forward)).toEqual([digest('9'), digest('a')]); // env-b 字典序先于 env-one
});
