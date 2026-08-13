import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { PermissionFact } from '@/api/types';

/** placeholder 数据（Phase 1；联调后由 /permissions 返回，映射 PermissionFact） */
const PLACEHOLDER_PERMISSIONS: PermissionFact[] = [
  {
    subject: { type: 'agent_asset', id: 'ast-01h2kd93nf' },
    delegated_user: { user_id: 'u-1024', token_ref: 'ref://delegated/…', purpose: 'contract-review' },
    domain: 'network',
    action: 'http.request',
    resource: { type: 'endpoint', value: 'api.example.com:443/orders/**' },
    effect: 'allow',
    conditions: { methods: ['GET'], purpose: 'contract-review', ttl: 300 },
    state: 'effective',
    authority: 'siq-gateway',
    authority_revision: 'gw-rev-4821',
    evidence_ids: ['ev-0001', 'ev-0002'],
    valid_from: '2026-08-01T00:00:00Z',
    valid_until: '2026-09-01T00:00:00Z',
  },
  {
    subject: { type: 'agent_asset', id: 'ast-01h2kd93nf' },
    domain: 'filesystem',
    action: 'fs.write',
    resource: { type: 'path', value: '/srv/siq/legal/reviews/' },
    effect: 'deny',
    state: 'declared',
    authority: 'openshell',
    authority_revision: 'os-pol-9910',
    evidence_ids: ['ev-0003'],
  },
  {
    subject: { type: 'identity_binding', id: 'ib-u1024-agent01' },
    delegated_user: { user_id: 'u-1024', token_ref: 'ref://delegated/…' },
    domain: 'data_scope',
    action: 'data.query',
    resource: { type: 'namespace', value: 'sales:eu' },
    effect: 'allow',
    conditions: { ttl: 120 },
    state: 'observed',
    authority: 'siq-iam',
    evidence_ids: ['ev-0004', 'ev-0005'],
  },
];

const effectTag = { allow: 'tag-ok', deny: 'tag-err' } as const;
const stateTag = {
  declared: '', inferred: 'tag-info', observed: 'tag-info',
  effective: 'tag-ok', unknown: '',
} as const;

const columns: TableColumn<PermissionFact>[] = [
  {
    key: 'subject',
    header: '主体',
    render: (f) => (
      <>
        <span className="mono">{f.subject.id}</span>{' '}
        <span className="tag tag-info">{f.subject.type}</span>
      </>
    ),
  },
  {
    key: 'delegated',
    header: '委托用户',
    render: (f) => f.delegated_user?.user_id ?? '—',
  },
  {
    key: 'domain_action',
    header: '域 / 动作',
    render: (f) => (
      <>
        <span className="tag">{f.domain}</span> {f.action}
      </>
    ),
  },
  { key: 'resource', header: '资源', render: (f) => <span className="mono">{f.resource.value}</span> },
  {
    key: 'effect',
    header: '效果',
    render: (f) => <span className={`tag ${effectTag[f.effect]}`}>{f.effect}</span>,
  },
  {
    key: 'state',
    header: '状态',
    render: (f) => <span className={`tag ${stateTag[f.state]}`}>{f.state}</span>,
  },
  { key: 'authority', header: '权威源', render: (f) => f.authority },
];

export default function PermissionsPage() {
  const facts = useApiList<PermissionFact>('/permissions', PLACEHOLDER_PERMISSIONS);

  return (
    <section>
      <PageHeader
        title="权限视图"
        description="来自各权威源的权限事实（PermissionFact，设计文档 §12.3）：主体、委托用户、动作与效果。有效数据范围 = Agent 自身权限 ∩ 调用用户数据范围。"
        connection={facts.status}
        connectionError={facts.error}
      />
      {facts.status === 'disconnected' ? (
        <DisconnectedNotice error={facts.error} onRetry={facts.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={facts.rows}
        rowKey={(f) => `${f.subject.id}:${f.domain}:${f.action}:${f.resource.value}`}
      />
    </section>
  );
}
