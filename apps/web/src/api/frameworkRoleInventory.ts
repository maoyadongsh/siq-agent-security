/**
 * 企业框架—角色分页清单（ENT-018-FRAMEWORK-TREE-UI）。
 *
 * 合同：packages/contracts/enterprise-framework-role-inventory.v1.md
 * GET /api/v1/framework-role-inventory（只读；agent:read + env:read；
 * 租户仅来自认证身份，客户端不得传 tenant_id 或任何身份覆盖参数）。
 *
 * 响应不证明进程正在运行、技能已加载或权限已生效；本模块只做严格核验，
 * 异常响应直接抛错，绝不回退为空列表或默认成功。
 */

import { get } from './client';
import { parseFrameworkSource, type FrameworkSourceView } from './frameworkSource';

export interface FrameworkRoleInventoryItem {
  asset_id: string;
  name: string;
  reported_framework: string;
  asset_status: string;
  /** 完整 enterprise-framework-source-view/v1 投影，asset_id 必须匹配本项 */
  framework_source: FrameworkSourceView;
}

export interface FrameworkRoleInventoryPage {
  schema_version: 'enterprise-framework-role-inventory/v1' | 'enterprise-framework-role-inventory/v2';
  coverage: 'page_of_tenant_assets';
  items: FrameworkRoleInventoryItem[];
  next_cursor: string | null;
}

export interface FrameworkRoleInventoryQuery {
  /** 已应用的环境过滤（保留原值，不做全量拉取） */
  environmentId?: string;
  /** 已应用的设备过滤 */
  deviceId?: string;
  /** 上一页末尾资产 ID；首页不传 */
  cursor?: string;
  /** 1..100，默认 50；不得调高上限冒充组织全量 */
  limit?: number;
}

const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const exact = (v: Record<string, unknown>, keys: readonly string[]) =>
  Object.keys(v).length === keys.length && keys.every(key => Object.hasOwn(v, key));
const assetId = (v: unknown): v is string => typeof v === 'string' && /^agt_[A-Za-z0-9_-]{1,60}$/.test(v);
const text = (v: unknown, max: number): v is string => typeof v === 'string' && v.length <= max;
const filterId = (v: string) => v.length >= 1 && v.length <= 64;

function parseItem(value: unknown, query: FrameworkRoleInventoryQuery): FrameworkRoleInventoryItem {
  if (!object(value) || !exact(value, ['asset_id', 'name', 'reported_framework', 'asset_status', 'framework_source'])
    || !assetId(value.asset_id) || !text(value.name, 512)
    || !text(value.reported_framework, 64) || !value.reported_framework
    || !text(value.asset_status, 64) || !value.asset_status) {
    throw new Error('框架角色清单响应无法核验');
  }
  // 来源投影的 asset_id 必须匹配所属清单项；版本/状态/来源语义不符即抛错。
  const source = parseFrameworkSource(value.framework_source, value.asset_id);
  // 已应用的环境/设备过滤：有来源的记录必须与过滤一致（无来源记录无法据此核对，合同允许保留）。
  if (source.status === 'historical_reported_source' && source.source) {
    if (query.environmentId && source.source.environment_id !== query.environmentId
      || query.deviceId && source.source.device_id !== query.deviceId) {
      throw new Error('框架角色清单响应无法核验');
    }
  }
  return value as unknown as FrameworkRoleInventoryItem;
}

export function parseFrameworkRoleInventory(value: unknown, query: FrameworkRoleInventoryQuery = {}): FrameworkRoleInventoryPage {
  const fail = () => { throw new Error('框架角色清单响应无法核验'); };
  if (!object(value) || !exact(value, ['schema_version', 'items', 'next_cursor', 'coverage'])
    || !['enterprise-framework-role-inventory/v1', 'enterprise-framework-role-inventory/v2'].includes(String(value.schema_version))
    || value.coverage !== 'page_of_tenant_assets'
    || !Array.isArray(value.items) || value.items.length > 100) return fail();
  const items = value.items.map(item => parseItem(item, query));
  if (value.schema_version === 'enterprise-framework-role-inventory/v1'
    && items.some(item => item.framework_source.schema_version !== 'enterprise-framework-source-view/v1')) return fail();
  // 合同要求按资产 ID 严格升序；cursor 之后不得出现 <= cursor 的项。
  for (let index = 0; index < items.length; index += 1) {
    const id = items[index].asset_id;
    if (query.cursor && id <= query.cursor) return fail();
    if (index > 0 && id <= items[index - 1].asset_id) return fail();
  }
  if (value.next_cursor !== null
    && (!assetId(value.next_cursor) || items.length === 0 || value.next_cursor !== items[items.length - 1].asset_id)) {
    return fail();
  }
  return value as unknown as FrameworkRoleInventoryPage;
}

export async function getFrameworkRoleInventory(query: FrameworkRoleInventoryQuery = {}): Promise<FrameworkRoleInventoryPage> {
  const limit = query.limit ?? 50;
  if (!Number.isInteger(limit) || limit < 1 || limit > 100
    || (query.environmentId !== undefined && !filterId(query.environmentId))
    || (query.deviceId !== undefined && !filterId(query.deviceId))
    || (query.cursor !== undefined && !assetId(query.cursor))) {
    throw new Error('框架角色清单请求参数无效');
  }
  const value = await get<unknown>('/framework-role-inventory', {
    query: {
      environment_id: query.environmentId || undefined,
      device_id: query.deviceId || undefined,
      cursor: query.cursor,
      limit,
    },
  });
  return parseFrameworkRoleInventory(value, query);
}
