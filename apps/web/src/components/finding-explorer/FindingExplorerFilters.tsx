/**
 * ENT-018-FINDINGS-UI：风险筛选条（级别/状态/域下拉 + 文本搜索 + 清除）。
 * AND 组合，仅作用于已加载记录；控件全部有可访问名称并可键盘操作。
 */
import type { Finding } from '@/api/types';
import {
  EMPTY_FINDING_FILTERS,
  FINDING_SEVERITIES,
  FINDING_STATUSES,
  hasActiveFindingFilters,
  listFindingDomains,
  severityLabel,
  statusLabel,
  type FindingFilters,
} from './findingExplorer';

interface FindingExplorerFiltersProps {
  rows: readonly Finding[];
  filters: FindingFilters;
  onChange: (next: FindingFilters) => void;
}

export default function FindingExplorerFilters({ rows, filters, onChange }: FindingExplorerFiltersProps) {
  const domains = listFindingDomains(rows);
  const patch = (partial: Partial<FindingFilters>) => onChange({ ...filters, ...partial });

  return (
    <div className="finding-explorer-filters" role="group" aria-label="风险筛选（仅作用于已加载记录）">
      <label className="finding-explorer-field">
        <span className="finding-explorer-field-label">风险级别</span>
        <select value={filters.severity} onChange={(event) => patch({ severity: event.target.value })}>
          <option value="">全部级别</option>
          {FINDING_SEVERITIES.map((severity) => (
            <option key={severity} value={severity}>
              {severityLabel(severity)}（{severity}）
            </option>
          ))}
        </select>
      </label>
      <label className="finding-explorer-field">
        <span className="finding-explorer-field-label">处置状态</span>
        <select value={filters.status} onChange={(event) => patch({ status: event.target.value })}>
          <option value="">全部状态</option>
          {FINDING_STATUSES.map((status) => (
            <option key={status} value={status}>
              {status}（{statusLabel(status)}）
            </option>
          ))}
        </select>
      </label>
      <label className="finding-explorer-field">
        <span className="finding-explorer-field-label">风险域</span>
        <select value={filters.domain} onChange={(event) => patch({ domain: event.target.value })}>
          <option value="">全部风险域</option>
          {domains.map((domain) => (
            <option key={domain} value={domain}>
              {domain}
            </option>
          ))}
        </select>
      </label>
      <label className="finding-explorer-field finding-explorer-field-search">
        <span className="finding-explorer-field-label">搜索（风险 / 规则 / 资产 / 描述 / 建议）</span>
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
        disabled={!hasActiveFindingFilters(filters)}
        onClick={() => onChange({ ...EMPTY_FINDING_FILTERS })}
      >
        清除筛选
      </button>
    </div>
  );
}
