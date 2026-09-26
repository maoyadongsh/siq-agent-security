/**
 * ENT-018-BINDINGS-UI：运行时绑定筛选条（状态/后端/环境下拉 + 文本搜索 + 清除）。
 * AND 组合，仅作用于已加载记录；控件全部有可访问名称并可键盘操作。
 */
import type { RuntimeBindingRow } from '@/api/types';
import {
  EMPTY_BINDING_FILTERS,
  hasActiveBindingFilters,
  listBindingBackends,
  listBindingEnvironments,
  type BindingFilters,
} from './runtimeBindingExplorer';

interface RuntimeBindingFiltersProps {
  rows: readonly RuntimeBindingRow[];
  filters: BindingFilters;
  onChange: (next: BindingFilters) => void;
}

export default function RuntimeBindingFilters({ rows, filters, onChange }: RuntimeBindingFiltersProps) {
  const backends = listBindingBackends(rows);
  const environments = listBindingEnvironments(rows);
  const patch = (partial: Partial<BindingFilters>) => onChange({ ...filters, ...partial });

  return (
    <div className="rb-explorer-filters" role="group" aria-label="运行时绑定筛选（仅作用于已加载记录）">
      <label className="rb-explorer-field">
        <span className="rb-explorer-field-label">状态</span>
        <select value={filters.status} onChange={(event) => patch({ status: event.target.value })}>
          <option value="">全部状态</option>
          <option value="active">active</option>
          <option value="revoked">revoked</option>
        </select>
      </label>
      <label className="rb-explorer-field">
        <span className="rb-explorer-field-label">后端类型</span>
        <select value={filters.backend} onChange={(event) => patch({ backend: event.target.value })}>
          <option value="">全部后端</option>
          {backends.map((backend) => (
            <option key={backend} value={backend}>
              {backend}
            </option>
          ))}
        </select>
      </label>
      <label className="rb-explorer-field">
        <span className="rb-explorer-field-label">环境</span>
        <select value={filters.environment} onChange={(event) => patch({ environment: event.target.value })}>
          <option value="">全部环境</option>
          {environments.map((env) => (
            <option key={env} value={env}>
              {env}
            </option>
          ))}
        </select>
      </label>
      <label className="rb-explorer-field rb-explorer-field-search">
        <span className="rb-explorer-field-label">搜索（绑定 / 资产 / 实例 / 运行时目标 ID）</span>
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
        disabled={!hasActiveBindingFilters(filters)}
        onClick={() => onChange({ ...EMPTY_BINDING_FILTERS })}
      >
        清除筛选
      </button>
    </div>
  );
}
