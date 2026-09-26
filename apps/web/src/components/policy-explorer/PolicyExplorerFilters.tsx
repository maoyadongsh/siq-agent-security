/**
 * ENT-018-POLICIES-UI：策略筛选条（档位/状态下拉 + 未覆盖项 + 文本搜索 + 清除）。
 * AND 组合，仅作用于已加载记录；状态选项来自已加载记录的真实值。
 */
import type { PolicyRow } from '@/api/types';
import {
  EMPTY_POLICY_FILTERS,
  ENFORCEMENT_MODES,
  hasActivePolicyFilters,
  listPolicyStatuses,
  modeLabel,
  type PolicyFilters,
} from './policyExplorer';

interface PolicyExplorerFiltersProps {
  rows: readonly PolicyRow[];
  filters: PolicyFilters;
  onChange: (next: PolicyFilters) => void;
}

export default function PolicyExplorerFilters({ rows, filters, onChange }: PolicyExplorerFiltersProps) {
  const statuses = listPolicyStatuses(rows);
  const patch = (partial: Partial<PolicyFilters>) => onChange({ ...filters, ...partial });

  return (
    <div className="policy-explorer-filters" role="group" aria-label="策略筛选（仅作用于已加载记录）">
      <label className="policy-explorer-field">
        <span className="policy-explorer-field-label">期望执行档位</span>
        <select value={filters.mode} onChange={(event) => patch({ mode: event.target.value })}>
          <option value="">全部档位</option>
          {ENFORCEMENT_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {modeLabel(mode)}（{mode}）
            </option>
          ))}
        </select>
      </label>
      <label className="policy-explorer-field">
        <span className="policy-explorer-field-label">策略状态</span>
        <select value={filters.status} onChange={(event) => patch({ status: event.target.value })}>
          <option value="">全部状态</option>
          {statuses.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </label>
      <label className="policy-explorer-field">
        <span className="policy-explorer-field-label">后端未覆盖项</span>
        <select
          value={filters.unsupported}
          onChange={(event) => patch({ unsupported: event.target.value as PolicyFilters['unsupported'] })}
        >
          <option value="">全部</option>
          <option value="with">有报告项</option>
          <option value="empty">报告列表为空</option>
        </select>
      </label>
      <label className="policy-explorer-field policy-explorer-field-search">
        <span className="policy-explorer-field-label">搜索（名称 / 策略 ID / 目标资产 ID）</span>
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
        disabled={!hasActivePolicyFilters(filters)}
        onClick={() => onChange({ ...EMPTY_POLICY_FILTERS })}
      >
        清除筛选
      </button>
    </div>
  );
}
