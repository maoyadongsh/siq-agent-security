/**
 * ENT-018-FINDINGS-UI：风险列表容器。桌面为对齐网格便于比较，移动宽度折叠为卡片。
 * 不修改共享 SimpleTable；处置操作由页面经 renderActions 注入。
 */
import type { ReactNode } from 'react';
import type { Finding } from '@/api/types';
import FindingExplorerItem from './FindingExplorerItem';
import './finding-explorer.css';

interface FindingExplorerListProps {
  rows: readonly Finding[];
  renderActions?: (finding: Finding) => ReactNode;
}

export default function FindingExplorerList({ rows, renderActions }: FindingExplorerListProps) {
  return (
    <div className="finding-explorer-list" role="list" aria-label="风险列表">
      <div className="finding-explorer-head" aria-hidden="true">
        <span>级别</span>
        <span>规则</span>
        <span>关联资产</span>
        <span>风险</span>
        <span>状态</span>
        <span />
      </div>
      {rows.map((finding) => (
        <div role="listitem" key={finding.id} className="finding-explorer-row">
          <FindingExplorerItem finding={finding} renderActions={renderActions} />
        </div>
      ))}
    </div>
  );
}
