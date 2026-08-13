import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { Environment } from '@/api/types';

/** placeholder 数据（Phase 1；联调后由 /environments 返回） */
const PLACEHOLDER_ENVIRONMENTS: Environment[] = [
  {
    id: 'env-prod-k8s',
    tenant_id: 'siq-dev',
    name: '生产（K8s）',
    env_type: 'k8s',
    mode: 'enforce',
    risk_level: 'high',
    last_heartbeat_at: '2026-08-13T01:55:00Z',
  },
  {
    id: 'env-dev-docker',
    tenant_id: 'siq-dev',
    name: '开发（Docker）',
    env_type: 'container',
    mode: 'observe',
    risk_level: 'medium',
    last_heartbeat_at: '2026-08-12T18:30:00Z',
  },
  {
    id: 'env-sandbox',
    tenant_id: 'siq-dev',
    name: '隔离沙箱',
    env_type: 'container',
    mode: 'discovery',
    risk_level: 'low',
    last_heartbeat_at: null,
  },
];

const modeTag: Record<Environment['mode'], string> = {
  discovery: 'tag-info',
  observe: 'tag-info',
  recommend: 'tag-warn',
  enforce: 'tag-err',
};

const riskTag: Record<Environment['risk_level'], string> = {
  low: '',
  medium: 'tag-warn',
  high: 'tag-err',
};

const envTypeTag: Record<Environment['env_type'], string> = {
  host: '',
  container: 'tag-info',
  k8s: 'tag-info',
  account: 'tag-warn',
};

const columns: TableColumn<Environment>[] = [
  { key: 'name', header: '环境', render: (e) => <strong>{e.name}</strong> },
  { key: 'id', header: '环境 ID', render: (e) => <span className="mono">{e.id}</span> },
  {
    key: 'env_type',
    header: '类型',
    render: (e) => <span className={`tag ${envTypeTag[e.env_type]}`}>{e.env_type}</span>,
  },
  {
    key: 'mode',
    header: '运行模式',
    render: (e) => <span className={`tag ${modeTag[e.mode]}`}>{e.mode}</span>,
  },
  {
    key: 'risk_level',
    header: '风险级别',
    render: (e) => <span className={`tag ${riskTag[e.risk_level]}`}>{e.risk_level}</span>,
  },
  {
    key: 'last_heartbeat_at',
    header: '最近心跳',
    render: (e) => (e.last_heartbeat_at ? e.last_heartbeat_at : <span className="muted-text">—</span>),
  },
];

export default function EnvironmentsPage() {
  const environments = useApiList<Environment>('/environments', PLACEHOLDER_ENVIRONMENTS);

  return (
    <section>
      <PageHeader
        title="环境与 Connector"
        description="纳管环境与其运行模式 / 风险级别（设计文档 §26）：last_heartbeat_at 由 Edge 心跳回写，长期缺失表示 Connector 离线。"
        connection={environments.status}
        connectionError={environments.error}
      />
      {environments.status === 'disconnected' ? (
        <DisconnectedNotice error={environments.error} onRetry={environments.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={environments.rows}
        rowKey={(e) => e.id}
      />
    </section>
  );
}
