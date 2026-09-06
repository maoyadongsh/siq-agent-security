import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { AuditEvent } from '@/api/types';

/** 控制面不可达时的安全示例数据；已连接时由 GET /audit-events 覆盖 */
const PLACEHOLDER_EVENTS: AuditEvent[] = [
  {
    id: 'aud-00001',
    actor_type: 'user',
    actor_id: 'admin@siq.local',
    action: 'agent.confirm',
    resource_type: 'agent_asset',
    resource_id: 'agt-01h2kd93nf',
    decision: 'allow',
    request_id: 'req-8f2a',
    summary: {},
    created_at: '2026-08-12T09:30:00Z',
  },
  {
    id: 'aud-00002',
    actor_type: 'edge',
    actor_id: 'edge-node-01',
    action: 'evidence.batch.upload',
    resource_type: 'environment',
    resource_id: 'env-dev-docker',
    decision: 'allow',
    request_id: 'req-71bc',
    summary: { candidates: 2, evidence: 5, permission_facts: 0 },
    created_at: '2026-08-11T09:52:00Z',
  },
  {
    id: 'aud-00003',
    actor_type: 'user',
    actor_id: 'u-0001',
    action: 'finding.resolve',
    resource_type: 'finding',
    resource_id: 'fnd-0002',
    decision: 'allow',
    request_id: 'req-19de',
    summary: {},
    created_at: '2026-08-11T06:20:00Z',
  },
];

const decisionTag: Record<string, string> = {
  allow: 'tag-ok',
  deny: 'tag-err',
};

const columns: TableColumn<AuditEvent>[] = [
  { key: 'id', header: '事件 ID', render: (e) => <span className="mono">{e.id}</span> },
  { key: 'created_at', header: '发生时间', render: (e) => e.created_at },
  { key: 'action', header: '动作', render: (e) => <span className="mono">{e.action}</span> },
  {
    key: 'actor',
    header: '触发者',
    render: (e) => (
      <span title={e.actor_id}>
        {e.actor_type}:{e.actor_id}
      </span>
    ),
  },
  {
    key: 'resource',
    header: '对象',
    render: (e) => (
      <span className="mono">
        {e.resource_type}
        {e.resource_id ? `:${e.resource_id}` : ''}
      </span>
    ),
  },
  {
    key: 'decision',
    header: '决策',
    render: (e) => (
      <span className={`tag ${decisionTag[e.decision] ?? ''}`}>{e.decision}</span>
    ),
  },
];

export default function AuditPage() {
  const events = useApiList<AuditEvent>('/audit-events', PLACEHOLDER_EVENTS, {
    includeTotal: true,
  });

  return (
    <section>
      <PageHeader
        icon="audit"
        title="审计"
        description="只读查看经租户隔离和敏感信息处理的控制面审计事件。"
        connection={events.status}
        connectionError={events.error}
      />
      {events.status === 'disconnected' ? (
        <DisconnectedNotice error={events.error} onRetry={events.reload} />
      ) : null}
      {events.coverageText ? (
        <p className="list-coverage" role="status">
          {events.coverageText}
        </p>
      ) : null}
      <SimpleTable
        columns={columns}
        rows={events.rows}
        rowKey={(e) => e.id}
      />
      {events.hasMore ? (
        <div className="list-more">
          <button
            type="button"
            className="btn-sm"
            disabled={events.loadingMore}
            onClick={() => events.loadMore()}
          >
            {events.loadingMore ? '加载中…' : '加载更多'}
          </button>
        </div>
      ) : null}
    </section>
  );
}
