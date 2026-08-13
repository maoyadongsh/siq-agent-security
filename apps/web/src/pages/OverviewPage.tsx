import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import { useApiList } from '@/hooks/useApiList';
import { API_BASE } from '@/api/client';
import type { AgentAsset } from '@/api/types';

/** 总览统计（placeholder：Phase 1 后端未联调，联调后由 /overview 端点返回） */
const PLACEHOLDER_STATS = [
  { key: 'agents', label: '纳管智能体资产', value: '12' },
  { key: 'candidates', label: '待评审候选', value: '3' },
  { key: 'open_findings', label: '未处置风险', value: '5' },
  { key: 'effective_policies', label: '生效策略', value: '28' },
  { key: 'pending_changes', label: '待审批变更', value: '2' },
  { key: 'environments', label: '环境 / Connector', value: '4' },
];

export default function OverviewPage() {
  const agents = useApiList<AgentAsset>('/agents', []);

  return (
    <section>
      <PageHeader
        title="总览"
        description="智能体安全管控平台控制台：资产、权限、风险、策略、变更与审计的统一入口（设计文档 §20.1）。"
        connection={agents.status}
        connectionError={agents.error}
      />
      {agents.status === 'disconnected' ? (
        <DisconnectedNotice error={agents.error} onRetry={agents.reload}>
          控制面 API 未启动或未部署（VITE_API_BASE={API_BASE}）。
        </DisconnectedNotice>
      ) : null}
      <div className="stats-grid">
        {PLACEHOLDER_STATS.map((s) => (
          <div className="stat-card" key={s.key}>
            <div className="stat-value">{s.value}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <h2>说明</h2>
        <p className="page-desc">
          Phase 1 骨架：后端 Control API 尚未联调，本页数据为本地 placeholder。
          路由、类型契约（src/api/types.ts）与 fetch 客户端（src/api/client.ts）已就绪，
          联调后各页面将自动切换为真实数据。
        </p>
      </div>
    </section>
  );
}
