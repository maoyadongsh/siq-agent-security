/**
 * ENT-018-POLICIES-UI：策略列表容器。桌面为对齐网格便于比较，≤1024px 折叠为卡片。
 */
import type { PolicyRow } from '@/api/types';
import PolicyExplorerItem from './PolicyExplorerItem';
import './policy-explorer.css';

interface PolicyExplorerListProps {
  rows: readonly PolicyRow[];
}

export default function PolicyExplorerList({ rows }: PolicyExplorerListProps) {
  return (
    <div className="policy-explorer-list" role="list" aria-label="期望策略列表">
      <div className="policy-explorer-head" aria-hidden="true">
        <span>名称</span>
        <span>版本</span>
        <span>期望档位</span>
        <span>状态</span>
        <span>未覆盖项</span>
        <span>目标资产</span>
        <span />
      </div>
      {rows.map((policy) => (
        <div role="listitem" key={policy.id} className="policy-explorer-row">
          <PolicyExplorerItem policy={policy} />
        </div>
      ))}
    </div>
  );
}
