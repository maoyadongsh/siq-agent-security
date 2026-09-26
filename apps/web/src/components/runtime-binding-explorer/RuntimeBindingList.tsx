/**
 * ENT-018-BINDINGS-UI：运行时绑定列表容器。桌面为对齐网格便于比较，移动宽度折叠为卡片。
 * 不修改共享 SimpleTable；处置操作由页面经 renderActions 注入。
 */
import type { ReactNode } from 'react';
import type { RuntimeBindingRow } from '@/api/types';
import RuntimeBindingItem from './RuntimeBindingItem';
import './runtime-binding-explorer.css';

interface RuntimeBindingListProps {
  rows: readonly RuntimeBindingRow[];
  renderActions?: (binding: RuntimeBindingRow) => ReactNode;
}

export default function RuntimeBindingList({ rows, renderActions }: RuntimeBindingListProps) {
  return (
    <div className="rb-explorer-list" role="list" aria-label="运行时绑定列表">
      <div className="rb-explorer-head" aria-hidden="true">
        <span>绑定 ID</span>
        <span>资产</span>
        <span>实例</span>
        <span>环境</span>
        <span>后端</span>
        <span>运行时目标</span>
        <span>状态</span>
        <span />
      </div>
      {rows.map((binding) => (
        <div role="listitem" key={binding.id} className="rb-explorer-row">
          <RuntimeBindingItem binding={binding} renderActions={renderActions} />
        </div>
      ))}
    </div>
  );
}
