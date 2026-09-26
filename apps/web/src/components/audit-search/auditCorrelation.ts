/**
 * CL-06-AUDIT-CORRELATION-UI：从真实审计事件发起精确关联查询的纯函数层。
 *
 * 语义边界：
 * - 「查询同请求」= 仅 request_id 精确相等；「查询同对象」= resource_type + resource_id
 *   同时精确相等（对象类型必须一起查询，避免跨类型同名 ID 混淆）；
 * - 关联操作生成全新条件：目标字段取该行原值，其余字段一律为空，
 *   不与上次已应用条件 AND，避免误以为无关联记录；
 * - 原值逐字保留：不 trim、不转小写、不截断；空格、中文、&、+、#、引号都只是匹配数据；
 * - 缺失、空值、异常类型、超长值不生成可操作条件，调用方不得回退查询全量；
 * - 相同标识仅表示标识相等，不是完整调用链、执行成功或防护效果证明。
 */
import {
  codePointLength,
  EMPTY_AUDIT_FILTERS,
  type AuditSearchFilters,
} from './auditSearch';
import type { AuditEvent } from '@/api/types';

/** 关联操作类型：同请求 / 同对象。 */
export type AuditCorrelationKind = 'request' | 'resource';

/** 关联操作可用性：仅真实 connected 结果中的有效标识可操作。 */
export interface AuditCorrelationAction {
  kind: AuditCorrelationKind;
  /** 可访问名称包含行标识，能区分操作及所选行 */
  accessibleName: string;
  /** 全新条件：只含目标字段原值，其余字段为空 */
  filters: AuditSearchFilters;
}

/** 字段原值是否可用作精确匹配条件：字符串、非空、长度符合合同上限。 */
function isUsableIdentifier(value: unknown, max: number): value is string {
  return typeof value === 'string' && value !== '' && codePointLength(value) <= max;
}

/**
 * 为一条真实审计事件计算可用的关联操作。
 * 缺失/空值/异常类型/超长值返回 null（调用方保持文本/未提供提示，不生成按钮）。
 */
export function auditCorrelationActions(event: AuditEvent): AuditCorrelationAction[] {
  const actions: AuditCorrelationAction[] = [];
  const requestId = event.request_id;
  if (isUsableIdentifier(requestId, 64)) {
    actions.push({
      kind: 'request',
      accessibleName: `查询同请求：${requestId}`,
      filters: { ...EMPTY_AUDIT_FILTERS, request_id: requestId },
    });
  }
  const resourceType = event.resource_type;
  const resourceId = event.resource_id;
  if (isUsableIdentifier(resourceType, 32) && isUsableIdentifier(resourceId, 64)) {
    actions.push({
      kind: 'resource',
      accessibleName: `查询同对象：${resourceType}:${resourceId}`,
      filters: { ...EMPTY_AUDIT_FILTERS, resource_type: resourceType, resource_id: resourceId },
    });
  }
  return actions;
}

/**
 * 关联操作生成的全新已应用条件：目标字段取该行原值，其余字段清空。
 * 与 auditFiltersEqual 配合：同条件重复点击走「不重复请求」路径。
 */
export function auditCorrelationFilters(
  event: AuditEvent,
  kind: AuditCorrelationKind,
): AuditSearchFilters | null {
  const action = auditCorrelationActions(event).find((a) => a.kind === kind);
  return action ? action.filters : null;
}

/** 关联操作会替换当前查询条件——用于操作前的明确说明文案。 */
export const AUDIT_CORRELATION_NOTE =
  '关联查询会替换当前查询条件（其余条件清空），仅按标识精确匹配；相同标识不代表完整调用链或防护效果已验证。';
