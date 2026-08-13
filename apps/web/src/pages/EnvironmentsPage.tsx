import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { Environment } from '@/api/types';

/** placeholder 数据（Phase 1；联调后由 /environments 返回） */
const PLACEHOLDER_ENVIRONMENTS: Environment[] = [
  {
    environment_id: 'env-prod-k8s',
    name: '生产（K8s）',
    kind: 'kubernetes',
    status: 'healthy',
    connector_version: 'kubernetes/v1.2.0',
    last_seen_at: '2026-08-13T01:55:00Z',
    description: '生产命名空间 siq-prod，纳管全部生产智能体资产',
  },
  {
    environment_id: 'env-dev-docker',
    name: '开发（Docker）',
    kind: 'docker',
    status: 'degraded',
    connector_version: 'docker/v1.1.0',
    last_seen_at: '2026-08-12T18:30:00Z',
    description: 'Connector 版本落后，需升级至 v1.2.0（风险中心 fnd-003）',
  },
  {
    environment_id: 'env-edge-hermes',
    name: 'Edge（Hermes）',
    kind: 'hermes',
    status: 'healthy',
    connector_version: 'hermes/v1.0.3',
    last_seen_at: '2026-08-13T01:58:00Z',
    description: 'Hermes Profile 直采，含未纳管候选（needs_review: 1）',
  },
  {
    environment_id: 'env-sandbox',
    name: '隔离沙箱',
    kind: 'sandbox',
    status: 'unknown',
    last_seen_at: '2026-08-11T10:00:00Z',
    description: '可疑资产隔离区（Offboarding 期间）',
  },
];

const statusTag: Record<Environment['status'], string> = {
  healthy: 'tag-ok',
  degraded: 'tag-warn',
  unknown: '',
  offline: 'tag-err',
};

const kindTag: Record<Environment['kind'], string> = {
  kubernetes: 'tag-info',
  docker: 'tag-info',
  systemd: '',
  hermes: 'tag-info',
  siq_hub: '',
  sandbox: 'tag-warn',
};

const columns: TableColumn<Environment>[] = [
  { key: 'name', header: '环境', render: (e) => <strong>{e.name}</strong> },
  { key: 'environment_id', header: '环境 ID', render: (e) => <span className="mono">{e.environment_id}</span> },
  { key: 'kind', header: '类型', render: (e) => <span className={`tag ${kindTag[e.kind]}`}>{e.kind}</span> },
  {
    key: 'status',
    header: '状态',
    render: (e) => <span className={`tag ${statusTag[e.status]}`}>{e.status}</span>,
  },
  { key: 'connector', header: 'Connector', render: (e) => e.connector_version ?? '—' },
  { key: 'last_seen', header: '最近在线', render: (e) => e.last_seen_at ?? '—' },
  { key: 'description', header: '说明', render: (e) => e.description ?? '—' },
];

export default function EnvironmentsPage() {
  const environments = useApiList<Environment>('/environments', PLACEHOLDER_ENVIRONMENTS);

  return (
    <section>
      <PageHeader
        title="环境与 Connector"
        description="纳管环境与其 Edge Connector 版本/健康状态（设计文档 §26）：Connector 只产生候选与证据，不直接创建纳管资产。"
        connection={environments.status}
        connectionError={environments.error}
      />
      {environments.status === 'disconnected' ? (
        <DisconnectedNotice error={environments.error} onRetry={environments.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={environments.rows}
        rowKey={(e) => e.environment_id}
      />
    </section>
  );
}
