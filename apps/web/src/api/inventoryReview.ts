import { get } from './client';
import type { AgentAsset } from './types';

export interface InventoryAccess { schema_version: 'inventory-access/v1'; can_confirm: boolean; can_discover: boolean; can_manage_policy: boolean }
export async function inventoryAccess(): Promise<InventoryAccess> {
  const value = await get<InventoryAccess>('/inventory/access');
  if (!value || value.schema_version !== 'inventory-access/v1' || typeof value.can_confirm !== 'boolean' || typeof value.can_discover !== 'boolean' || typeof value.can_manage_policy !== 'boolean') throw new Error('无法核对资产操作权限');
  return value;
}
const labels: Record<AgentAsset['status'], string> = {
  candidate: '待确认', needs_review: '需人工核查', confirmed: '已确认', managed: '已纳管', stale: '信息待更新', retired: '已退役', dismissed: '已驳回',
};
export const assetStatusLabel = (status: string) => labels[status as AgentAsset['status']] ?? '状态待核实';
export const pendingCandidate = (asset: AgentAsset) => ['candidate', 'needs_review'].includes(asset.status);
export function assertReviewReadback(value: AgentAsset, id: string, action: 'confirm' | 'dismiss', role: string) {
  if (!value || value.id !== id || value.status !== (action === 'confirm' ? 'confirmed' : 'dismissed')
    || (action === 'confirm' && role && value.role !== role)) throw new Error('处理结果尚未核对，请读取当前状态');
  return value;
}
export const inventoryStamp = (s: string) => {
  const dt = new Date(/[Zz]|[+-]\d\d:\d\d$/.test(s) ? s : `${s}Z`);
  return Number.isFinite(dt.getTime()) ? dt.toLocaleString('zh-CN', { hour12: false }) : '时间未知';
};
