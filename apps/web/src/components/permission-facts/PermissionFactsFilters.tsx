/**
 * ENT-014-UI：组合筛选条（authority 按钮 + 状态/权限域下拉 + 文本搜索 + 清除）。
 * 筛选均为 AND 组合，只作用于已加载记录；控件全部可键盘操作并带 label。
 */
import type { PermissionFactRow } from '@/api/types';
import { permissionStateLabel } from '@/ui/verification';
import {
  EMPTY_FILTERS,
  PERMISSION_FACT_STATES,
  hasActiveFilters,
  listAuthorities,
  listDomains,
  type PermissionFactFilters,
} from './permissionFacts';

/** 权限域中文名（未知域显示原始值）。 */
export const DOMAIN_LABELS: Record<string, string> = {
  filesystem: '文件',
  network: '网络',
  process: '进程',
  model: '模型',
  credential: '凭据',
  data_scope: '数据范围',
  tool: '工具',
  business: '业务',
  resource: '资源',
  control_plane: '控制面',
};

export function domainLabel(domain: string): string {
  return Object.hasOwn(DOMAIN_LABELS, domain) ? DOMAIN_LABELS[domain] : domain;
}

interface PermissionFactsFiltersProps {
  rows: readonly PermissionFactRow[];
  filters: PermissionFactFilters;
  onChange: (next: PermissionFactFilters) => void;
}

export default function PermissionFactsFilters({ rows, filters, onChange }: PermissionFactsFiltersProps) {
  const authorities = listAuthorities(rows);
  const domains = listDomains(rows);
  const authorityCounts = new Map<string, number>();
  for (const row of rows) {
    authorityCounts.set(row.authority, (authorityCounts.get(row.authority) ?? 0) + 1);
  }

  const patch = (partial: Partial<PermissionFactFilters>) => onChange({ ...filters, ...partial });

  return (
    <div className="pf-filters" role="group" aria-label="权限事实筛选（仅作用于已加载记录）">
      <div className="pf-filter-row" role="group" aria-label="按权威来源筛选">
        <button
          type="button"
          className={`btn-sm ${filters.authority === '' ? 'btn-active' : 'btn-ghost'}`}
          onClick={() => patch({ authority: '' })}
        >
          全部来源（{rows.length}）
        </button>
        {authorities.map((authority) => (
          <button
            key={authority}
            type="button"
            className={`btn-sm ${filters.authority === authority ? 'btn-active' : 'btn-ghost'}`}
            onClick={() => patch({ authority })}
          >
            {authority}（{authorityCounts.get(authority) ?? 0}）
          </button>
        ))}
      </div>
      <div className="pf-filter-row">
        <label className="pf-field">
          <span className="pf-field-label">事实状态</span>
          <select
            value={filters.state}
            onChange={(event) => patch({ state: event.target.value })}
          >
            <option value="">全部状态</option>
            {PERMISSION_FACT_STATES.map((state) => (
              <option key={state} value={state}>
                {permissionStateLabel(state)}
              </option>
            ))}
          </select>
        </label>
        <label className="pf-field">
          <span className="pf-field-label">权限域</span>
          <select
            value={filters.domain}
            onChange={(event) => patch({ domain: event.target.value })}
          >
            <option value="">全部权限域</option>
            {domains.map((domain) => (
              <option key={domain} value={domain}>
                {domainLabel(domain)}
              </option>
            ))}
          </select>
        </label>
        <label className="pf-field pf-field-search">
          <span className="pf-field-label">搜索（主体 / 动作 / 资源 / 来源）</span>
          <input
            type="search"
            value={filters.query}
            placeholder="仅搜索已加载记录"
            onChange={(event) => patch({ query: event.target.value })}
          />
        </label>
        <button
          type="button"
          className="btn-sm"
          disabled={!hasActiveFilters(filters)}
          onClick={() => onChange({ ...EMPTY_FILTERS })}
        >
          清除筛选
        </button>
      </div>
    </div>
  );
}
