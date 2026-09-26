/**
 * ENT-014-UI：五类权限事实状态概览。
 * 只在 connected 状态渲染；计数仅统计已加载记录，不是组织全量。
 * effective 计数不代表「阻断已验证」，解释文案固定说明边界。
 */
import type { PermissionFactRow } from '@/api/types';
import { permissionStateLabel } from '@/ui/verification';
import {
  PERMISSION_FACT_STATES,
  countByState,
  permissionStateExplanation,
} from './permissionFacts';

interface PermissionFactsOverviewProps {
  rows: readonly PermissionFactRow[];
}

export default function PermissionFactsOverview({ rows }: PermissionFactsOverviewProps) {
  const counts = countByState(rows);
  return (
    <section className="pf-overview" aria-label="权限事实状态概览（仅统计已加载记录）">
      <p className="pf-overview-note">
        以下为已加载 {rows.length} 条记录的分类统计，不代表组织全量；「生效」仅是后端记录的事实层级，不等于已通过行为阻断验证。
      </p>
      <ul className="pf-overview-grid">
        {PERMISSION_FACT_STATES.map((state) => (
          <li key={state} className={`pf-state-card pf-state-${state}`}>
            <span className={`state-tag ${state}`}>{permissionStateLabel(state)}</span>
            <span className="pf-state-count" aria-label={`${permissionStateLabel(state)} ${counts[state]} 条`}>
              {counts[state]}
            </span>
            <span className="pf-state-expl">{permissionStateExplanation(state)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
