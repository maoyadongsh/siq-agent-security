import type { ReactNode } from 'react';

/**
 * 最简单的表格容器（Phase 1：不做排序/分页/虚拟滚动，
 * 仅用于骨架联调时呈现后端列表数据）。
 */
export interface TableColumn<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
}

interface SimpleTableProps<T> {
  columns: TableColumn<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  emptyText?: string;
}

export default function SimpleTable<T>({
  columns,
  rows,
  rowKey,
  emptyText = '暂无数据',
}: SimpleTableProps<T>) {
  if (rows.length === 0) {
    return <p className="table-empty">{emptyText}</p>;
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key}>{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)}>
              {columns.map((col) => (
                <td key={col.key}>{col.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
