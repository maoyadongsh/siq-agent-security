import type { ReactNode } from 'react';
import { Icon } from '@/components/icons';

/**
 * 最简单的表格容器（不做排序/分页/虚拟滚动，仅呈现列表）。
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
  /** 行 class（如回执 deny 高亮）；企业列表页不传 */
  rowClassName?: (row: T) => string | undefined;
  onRowClick?: (row: T) => void;
}

export default function SimpleTable<T>({
  columns,
  rows,
  rowKey,
  emptyText = '暂无数据',
  rowClassName,
  onRowClick,
}: SimpleTableProps<T>) {
  if (rows.length === 0) {
    return (
      <div className="table-empty">
        <span className="empty-icon" aria-hidden="true">
          <Icon name="scan" size={20} />
        </span>
        <span>{emptyText}</span>
      </div>
    );
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
            {rows.map((row) => {
              const extra = rowClassName?.(row);
              const clickable = onRowClick ? ' clickable' : '';
              return (
                <tr
                  key={rowKey(row)}
                  className={`${extra ?? ''}${clickable}`.trim() || undefined}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                >
                  {columns.map((col) => (
                    <td key={col.key}>{col.render(row)}</td>
                  ))}
                </tr>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
