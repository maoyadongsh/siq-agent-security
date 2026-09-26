/**
 * ENT-018-POLICIES-UI：策略中心只读筛选的纯函数层。
 * 语义边界：
 * - 列表展示的是「期望策略」；实际生效需结合审批、部署及独立后端读回核对；
 * - enforcement_mode=block 是期望档位，不得显示为 effective/已生效；
 * - unsupported_by_backend 为空只说明本条响应未列出未覆盖项，不等于「全部支持」；
 * - selector 只读自身 agent_ids 属性；空 agent_ids 不等于全部资产；
 * - 筛选只作用于已加载记录，不代表组织全量。
 */

import type { PolicyRow } from '@/api/types';

export const ENFORCEMENT_MODES = ['audit_only', 'warn', 'block'] as const;

export const MODE_LABELS: Record<string, string> = {
  audit_only: '仅审计',
  warn: '告警',
  block: '阻断',
};

/** 原型安全的标签查表：__proto__/constructor/toString 等不会取到原型成员。 */
export function safeLookup(map: Record<string, string>, key: string): string | undefined {
  return Object.hasOwn(map, key) ? map[key] : undefined;
}

export function modeLabel(mode: string): string {
  return safeLookup(MODE_LABELS, mode) ?? mode;
}

/** 期望档位展示文案：明示是「期望」，不借用 effective/已生效语义。 */
export function modeExpectationText(mode: string): string {
  return `期望：${modeLabel(mode)}`;
}

export type UnsupportedFilter = '' | 'with' | 'empty';

export interface PolicyFilters {
  /** 期望执行档位；空串=全部 */
  mode: string;
  /** 策略状态（选项来自已加载记录的真实值）；空串=全部 */
  status: string;
  /** 未覆盖项：'' 全部 / 'with' 有报告项 / 'empty' 报告列表为空 */
  unsupported: UnsupportedFilter;
  /** 文本搜索：策略名称、策略 ID、目标资产 ID */
  query: string;
}

export const EMPTY_POLICY_FILTERS: PolicyFilters = { mode: '', status: '', unsupported: '', query: '' };

export function hasActivePolicyFilters(filters: PolicyFilters): boolean {
  return Boolean(filters.mode || filters.status || filters.unsupported || filters.query.trim());
}

/** 已加载记录中真实出现的状态值（不猜测状态机；原型安全）。 */
export function listPolicyStatuses(rows: readonly PolicyRow[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) {
    if (typeof row.status === 'string' && row.status) seen.add(row.status);
  }
  return Array.from(seen).sort((a, b) => a.localeCompare(b));
}

export type AgentIdsView =
  | { kind: 'ok'; ids: string[] }
  | { kind: 'missing' }
  | { kind: 'invalid' };

/**
 * 只读取 selector 自身的 agent_ids 属性：是字符串数组才展示；
 * 不遍历/展开其他字段；缺失或类型异常明确区分。
 */
export function extractAgentIds(selector: Record<string, unknown> | null | undefined): AgentIdsView {
  if (!selector || typeof selector !== 'object' || Array.isArray(selector)) return { kind: 'missing' };
  if (!Object.hasOwn(selector, 'agent_ids')) return { kind: 'missing' };
  const value = selector.agent_ids;
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    return { kind: 'invalid' };
  }
  return { kind: 'ok', ids: value };
}

function searchText(row: PolicyRow): string {
  const ids = extractAgentIds(row.selector);
  return [row.name, row.id, ...(ids.kind === 'ok' ? ids.ids : [])].join('\n').toLowerCase();
}

/**
 * AND 组合筛选（mode/status/unsupported/query 同时满足）。
 * 只覆盖已加载记录；返回新数组，不修改输入。
 */
export function filterPolicies(rows: readonly PolicyRow[], filters: PolicyFilters): PolicyRow[] {
  const query = filters.query.trim().toLowerCase();
  return rows.filter((row) => {
    if (filters.mode && row.enforcement_mode !== filters.mode) return false;
    if (filters.status && row.status !== filters.status) return false;
    if (filters.unsupported === 'with' && row.unsupported_by_backend.length === 0) return false;
    if (filters.unsupported === 'empty' && row.unsupported_by_backend.length > 0) return false;
    if (query && !searchText(row).includes(query)) return false;
    return true;
  });
}
