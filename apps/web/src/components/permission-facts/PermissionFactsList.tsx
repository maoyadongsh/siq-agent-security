/**
 * ENT-014-UI：权限事实列表。桌面为对齐网格便于比较，375px 下折叠为卡片。
 * 有效期提示依赖当前设备时间：每 60 秒刷新一次，卸载时清理计时器。
 */
import { useEffect, useState } from 'react';
import type { PermissionFactRow } from '@/api/types';
import PermissionFactItem from './PermissionFactItem';
import './permission-facts.css';

const NOW_REFRESH_MS = 60_000;

interface PermissionFactsListProps {
  rows: readonly PermissionFactRow[];
}

export default function PermissionFactsList({ rows }: PermissionFactsListProps) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), NOW_REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="pf-list" role="list" aria-label="权限事实列表">
      <div className="pf-list-head" aria-hidden="true">
        <span>权限域</span>
        <span>动作</span>
        <span>资源</span>
        <span>效果</span>
        <span>状态</span>
        <span>权威来源</span>
        <span>有效期</span>
        <span />
      </div>
      {rows.map((row) => (
        <div role="listitem" key={row.id} className="pf-list-item">
          <PermissionFactItem row={row} now={now} />
        </div>
      ))}
    </div>
  );
}
