import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { AgentAsset } from '@/api/types';

/** placeholder 数据（Phase 1，后端未联调；联调后由 /agents 返回） */
const PLACEHOLDER_AGENTS: AgentAsset[] = [
  {
    agent_id: 'ast-01h2kd93nf',
    name: 'siq_legal_advisor',
    role: 'contract-review',
    status: 'managed',
    framework: 'hermes',
    environment_id: 'env-prod-k8s',
    discovered_at: '2026-07-30T02:14:00Z',
    updated_at: '2026-08-12T09:30:00Z',
  },
  {
    agent_id: 'ast-02k8w1b3m7',
    name: 'ops_incident_responder',
    role: 'incident-response',
    status: 'onboarding',
    framework: 'openclaw',
    environment_id: 'env-prod-k8s',
    discovered_at: '2026-08-08T11:02:00Z',
  },
  {
    agent_id: 'ast-03q4z9p6c2',
    name: 'data_analyst_ghost',
    role: 'data-query',
    status: 'needs_review',
    framework: 'unknown',
    environment_id: 'env-dev-docker',
    discovered_at: '2026-08-10T23:47:00Z',
  },
  {
    agent_id: 'ast-04r7t2y8j5',
    name: 'finance_reporting_bot',
    role: 'reporting',
    status: 'managed',
    framework: 'hermes',
    environment_id: 'env-prod-k8s',
    discovered_at: '2026-06-18T08:05:00Z',
  },
];

const statusTag: Record<string, string> = {
  managed: 'tag-ok',
  onboarding: 'tag-info',
  needs_review: 'tag-warn',
  candidate: 'tag-warn',
  dismissed: 'tag-err',
  offboarding: 'tag-err',
};

const columns: TableColumn<AgentAsset>[] = [
  {
    key: 'name',
    header: '名称',
    render: (a) => <Link to={`/agents/${a.agent_id}`}>{a.name}</Link>,
  },
  { key: 'role', header: '角色', render: (a) => a.role ?? '—' },
  {
    key: 'status',
    header: '状态',
    render: (a) => (
      <span className={`tag ${statusTag[a.status] ?? ''}`}>{a.status}</span>
    ),
  },
  { key: 'framework', header: '框架', render: (a) => a.framework },
  { key: 'environment', header: '环境', render: (a) => a.environment_id ?? '—' },
  { key: 'updated_at', header: '更新时间', render: (a) => a.updated_at ?? a.discovered_at ?? '—' },
];

export default function AgentsPage() {
  const agents = useApiList<AgentAsset>('/agents', PLACEHOLDER_AGENTS);

  return (
    <section>
      <PageHeader
        title="智能体资产"
        description="由发现候选（AgentCandidate）纳管后的智能体资产清单：名称、角色、状态与框架（设计文档 §10）。"
        connection={agents.status}
        connectionError={agents.error}
      />
      {agents.status === 'disconnected' ? (
        <DisconnectedNotice error={agents.error} onRetry={agents.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={agents.rows}
        rowKey={(a) => a.agent_id}
      />
    </section>
  );
}
