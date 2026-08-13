import { Link, useParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';

/**
 * 智能体资产详情（占位）。
 * Phase 1 仅展示 ID 与来源信息；Phase 2 联调 GET /agents/:id 后
 * 渲染完整资产生命周期（候选→评审→纳管→变更→退役）。
 */
export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();

  return (
    <section>
      <PageHeader
        title="智能体资产详情"
        description="资产详情页为 Phase 1 占位：仅展示路由参数，待 Control API 联调后渲染完整信息。"
        connection="disconnected"
        connectionError="详情接口（GET /agents/:id）尚未联调"
      />
      <div className="card">
        <h2>资产标识</h2>
        <p>
          <span className="mono">agent_id: {id ?? '(missing)'}</span>
        </p>
        <p className="page-desc">
          后端联调后，此处将展示：来源候选（candidate_id）、发现证据（evidence_ids）、
          权限视图（PermissionFact）、风险条目（Finding）与策略执行状态（DesiredPolicy）。
        </p>
        <p>
          <Link to="/agents">← 返回智能体资产列表</Link>
        </p>
      </div>
    </section>
  );
}
