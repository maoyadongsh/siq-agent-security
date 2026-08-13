import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { EventEnvelope } from '@/api/types';

/** placeholder 数据（Phase 1；联调后由 /audit/events 返回，映射 EventEnvelope） */
const PLACEHOLDER_EVENTS: EventEnvelope[] = [
  {
    event_id: 'evt-00001',
    event_type: 'agent.candidate.discovered.v1',
    occurred_at: '2026-08-12T09:30:00Z',
    tenant_id: 'siq-dev',
    environment_id: 'env-dev-docker',
    actor: { actor_type: 'connector', actor_id: 'docker/v1.1.0' },
    resource_ref: 'candidate:docker:data_analyst_ghost',
    request_id: 'req-8f2a',
    schema_version: 1,
    payload: { candidate_id: 'docker:data_analyst_ghost@v1', framework: 'unknown' },
  },
  {
    event_id: 'evt-00002',
    event_type: 'policy.status.changed.v1',
    occurred_at: '2026-08-11T09:52:00Z',
    tenant_id: 'siq-dev',
    environment_id: 'env-prod-k8s',
    actor: { actor_type: 'human', actor_id: 'u-0001' },
    resource_ref: 'policy:pol-incident-responder:v3',
    request_id: 'req-71bc',
    schema_version: 1,
    payload: { change_id: 'chg-0092', from: 'approved', to: 'effective' },
  },
  {
    event_id: 'evt-00003',
    event_type: 'permission.fact.observed.v1',
    occurred_at: '2026-08-11T06:20:00Z',
    tenant_id: 'siq-dev',
    environment_id: 'env-edge-hermes',
    actor: { actor_type: 'edge', actor_id: 'edge-node-01' },
    resource_ref: 'agent_asset:ast-03q4z9p6c2',
    request_id: 'req-19de',
    schema_version: 1,
    payload: { domain: 'credential', effect: 'allow', state: 'observed' },
  },
];

const columns: TableColumn<EventEnvelope>[] = [
  { key: 'event_id', header: '事件 ID', render: (e) => <span className="mono">{e.event_id}</span> },
  { key: 'event_type', header: '事件类型', render: (e) => <span className="mono">{e.event_type}</span> },
  { key: 'occurred_at', header: '发生时间', render: (e) => e.occurred_at },
  { key: 'actor', header: '触发者', render: (e) => (e.actor ? `${e.actor.actor_type}:${e.actor.actor_id}` : '—') },
  { key: 'resource', header: '对象', render: (e) => <span className="mono">{e.resource_ref ?? '—'}</span> },
  { key: 'schema', header: '版本', render: (e) => `v${e.schema_version}` },
];

export default function AuditPage() {
  const events = useApiList<EventEnvelope>('/audit/events', PLACEHOLDER_EVENTS);

  return (
    <section>
      <PageHeader
        title="审计"
        description="领域事件统一信封（EventEnvelope，设计文档 §18.3）：消费者按 event_id 幂等处理，payload 已脱敏。"
        connection={events.status}
        connectionError={events.error}
      />
      {events.status === 'disconnected' ? (
        <DisconnectedNotice error={events.error} onRetry={events.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={events.rows}
        rowKey={(e) => e.event_id}
      />
    </section>
  );
}
