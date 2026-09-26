/**
 * ENT-018-FINDINGS-UI：风险中心只读筛选的纯函数层。
 * 语义边界：
 * - 筛选只作用于已加载记录，不代表组织全量；不得用列表长度推导总风险数；
 * - 确认（acknowledged）≠ 解决（resolved）；risk_accepted ≠ 风险已消除；
 * - 未知枚举值不丢记录、不冒充已解决；不修改输入数组或后端字段。
 */

import type { Finding } from '@/api/types';

export const FINDING_SEVERITIES = ['critical', 'high', 'medium', 'low', 'info'] as const;
export const FINDING_STATUSES = ['open', 'acknowledged', 'resolved', 'risk_accepted'] as const;

export const SEVERITY_LABELS: Record<string, string> = {
  critical: '严重',
  high: '高',
  medium: '中',
  low: '低',
  info: '提示',
};

/** 状态中文说明：仅翻译，不改变语义；确认不等于解决，接受不等于消除。 */
export const STATUS_LABELS: Record<string, string> = {
  open: '未处置',
  acknowledged: '已确认（不等于已解决）',
  resolved: '已解决（不等于独立验证阻断生效）',
  risk_accepted: '已接受风险（不等于风险已消除）',
};

export function severityLabel(severity: string): string {
  return Object.hasOwn(SEVERITY_LABELS, severity) ? SEVERITY_LABELS[severity] : severity;
}

export function statusLabel(status: string): string {
  return Object.hasOwn(STATUS_LABELS, status) ? STATUS_LABELS[status] : status;
}

/** 已终态（不可再确认/解决）；未知状态不视为终态，但也不冒充已解决。 */
export function isFinalStatus(status: string): boolean {
  return status === 'resolved' || status === 'risk_accepted';
}

export interface FindingFilters {
  /** 空串表示不筛选 */
  severity: string;
  status: string;
  domain: string;
  /** 文本搜索：风险 ID / 规则 ID / 关联资产 ID / 风险描述 / 修复建议 */
  query: string;
}

export const EMPTY_FINDING_FILTERS: FindingFilters = { severity: '', status: '', domain: '', query: '' };

export function hasActiveFindingFilters(filters: FindingFilters): boolean {
  return Boolean(filters.severity || filters.status || filters.domain || filters.query.trim());
}

/** 已加载记录中出现的风险域（跳过 null；原始值）。 */
export function listFindingDomains(rows: readonly Finding[]): string[] {
  const domains = new Set<string>();
  for (const row of rows) {
    if (row.domain) domains.add(row.domain);
  }
  return Array.from(domains).sort((a, b) => a.localeCompare(b));
}

function searchText(row: Finding): string {
  return [row.id, row.rule_id, row.asset_id ?? '', row.impact ?? '', row.remediation ?? '']
    .join('\n')
    .toLowerCase();
}

/**
 * AND 组合筛选（severity/status/domain/query 同时满足）。
 * 只覆盖传入的已加载记录；返回新数组，不修改输入。
 */
export function filterFindings(rows: readonly Finding[], filters: FindingFilters): Finding[] {
  const query = filters.query.trim().toLowerCase();
  return rows.filter((row) => {
    if (filters.severity && row.severity !== filters.severity) return false;
    if (filters.status && row.status !== filters.status) return false;
    if (filters.domain && row.domain !== filters.domain) return false;
    if (query && !searchText(row).includes(query)) return false;
    return true;
  });
}
