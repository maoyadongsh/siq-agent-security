/**
 * 框架配置实例树的分组纯函数（ENT-018-FRAMEWORK-TREE-UI）。
 *
 * 规则（合同 enterprise-framework-role-inventory.v1 + enterprise-framework-source.v1）：
 * - 仅 historical_reported_source 可归入配置实例组；
 * - 实例分组键 = environment_id + device_id + framework + instance_key，
 *   不用名称、摘要前缀或框架名称做唯一键；不同设备 instance_key 相同也分开；
 * - no_recorded_source 与 source_unavailable 分别归入「来源待确认」的独立分组；
 * - 同名角色不去重，以完整 asset_id 标识；
 * - 同一 asset_id 重复出现：内容一致则忽略重复；内容冲突则保留首条并显式标记
 *   conflict（不静默选择一个来源当作已核验结果）。
 */

import type { FrameworkRoleInventoryItem } from '@/api/frameworkRoleInventory';

export interface RoleEntry {
  item: FrameworkRoleInventoryItem;
  /** 同一 asset_id 在不同响应中内容不一致；显示不代表已核验，需刷新 */
  conflict: boolean;
}

export interface InstanceGroup {
  key: string;
  environmentId: string;
  deviceId: string;
  framework: string;
  instanceKey: string;
  deviceRevoked: boolean;
  roles: RoleEntry[];
}

export interface DeviceGroup {
  deviceId: string;
  deviceRevoked: boolean;
  instances: InstanceGroup[];
}

export interface EnvironmentGroup {
  environmentId: string;
  devices: DeviceGroup[];
}

export interface GroupedFrameworkRoles {
  environments: EnvironmentGroup[];
  /** status=no_recorded_source：没有来源记录，不代表未安装框架 */
  noRecordedSource: RoleEntry[];
  /** status=source_unavailable：记录存在但异常或证据不完整，不能按名称猜测归属 */
  sourceUnavailable: RoleEntry[];
  /** 内容冲突的重复资产条数（>0 时界面必须提示刷新） */
  conflictCount: number;
}

const signature = (item: FrameworkRoleInventoryItem): string => JSON.stringify([
  item.asset_id, item.name, item.reported_framework, item.asset_status, item.framework_source,
]);

export function groupFrameworkRoles(items: FrameworkRoleInventoryItem[]): GroupedFrameworkRoles {
  const seen = new Map<string, { signature: string; entry: RoleEntry }>();
  const instances = new Map<string, InstanceGroup>();
  const noRecordedSource: RoleEntry[] = [];
  const sourceUnavailable: RoleEntry[] = [];
  let conflictCount = 0;

  for (const item of items) {
    const existing = seen.get(item.asset_id);
    if (existing) {
      if (existing.signature !== signature(item)) {
        if (!existing.entry.conflict) {
          existing.entry.conflict = true;
          conflictCount += 1;
        }
      }
      continue; // 重复 asset_id 不重复渲染
    }
    const entry: RoleEntry = { item, conflict: false };
    seen.set(item.asset_id, { signature: signature(item), entry });

    const view = item.framework_source;
    if (view.status === 'historical_reported_source' && view.source) {
      const source = view.source;
      const key = JSON.stringify([source.environment_id, source.device_id, source.framework, source.instance_key]);
      let group = instances.get(key);
      if (!group) {
        group = {
          key,
          environmentId: source.environment_id,
          deviceId: source.device_id,
          framework: source.framework,
          instanceKey: source.instance_key,
          deviceRevoked: source.device_revoked,
          roles: [],
        };
        instances.set(key, group);
      }
      group.roles.push(entry);
      // 同一设备跨页重复出现时，凭据吊销是设备级事实：任一页标记吊销即保持标记。
      if (source.device_revoked) group.deviceRevoked = true;
    } else if (view.status === 'source_unavailable') {
      sourceUnavailable.push(entry);
    } else {
      noRecordedSource.push(entry);
    }
  }

  // 环境 → 设备 → 实例层级；按键排序保证展示稳定，与到达顺序无关。
  const environments = new Map<string, EnvironmentGroup>();
  const devices = new Map<string, DeviceGroup>();
  const sortedInstances = [...instances.values()].sort((a, b) =>
    a.environmentId.localeCompare(b.environmentId)
    || a.deviceId.localeCompare(b.deviceId)
    || a.instanceKey.localeCompare(b.instanceKey));
  for (const group of sortedInstances) {
    group.roles.sort((a, b) => a.item.asset_id.localeCompare(b.item.asset_id));
    let environment = environments.get(group.environmentId);
    if (!environment) {
      environment = { environmentId: group.environmentId, devices: [] };
      environments.set(group.environmentId, environment);
    }
    const deviceKey = JSON.stringify([group.environmentId, group.deviceId]);
    let device = devices.get(deviceKey);
    if (!device) {
      device = { deviceId: group.deviceId, deviceRevoked: group.deviceRevoked, instances: [] };
      devices.set(deviceKey, device);
      environment.devices.push(device);
    }
    if (group.deviceRevoked) device.deviceRevoked = true;
    device.instances.push(group);
  }

  return {
    environments: [...environments.values()],
    noRecordedSource,
    sourceUnavailable,
    conflictCount,
  };
}
