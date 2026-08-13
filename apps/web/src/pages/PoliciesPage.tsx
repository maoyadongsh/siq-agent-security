import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { DesiredPolicy } from '@/api/types';

/** placeholder 数据（Phase 1；联调后由 /policies 返回） */
const PLACEHOLDER_POLICIES: DesiredPolicy[] = [
  {
    policy_id: 'pol-legal-contract-review',
    selector: {
      agent_ids: ['ast-01h2kd93nf'],
      environment_ids: ['env-prod-k8s'],
      labels: { role: 'contract-review' },
    },
    filesystem: { read_only: ['/etc', '/var/run'], read_write: ['/srv/siq/legal/reviews/'] },
    network: [
      { endpoint: 'api.example.com:443/orders/**', effect: 'allow', methods: ['GET'], purpose: 'contract-review' },
      { endpoint: '0.0.0.0:0', effect: 'deny' },
    ],
    process: { run_as: '65532:65532', forbid_privilege_escalation: true, seccomp_profile: 'siq-default-v1' },
    model_routing: { allowed_models: ['hermes-pro', 'hermes-lite'], provider: 'siq-model-gw' },
    tools: ['tool:pdf-extract', 'tool:risk-score'],
    tool_policies: { 'tool:pdf-extract': { max_pages: 500 } },
    data_scope_refs: ['ds-sales-eu'],
    secrets: [{ ref: 'cred:siq-gateway/api-key', purpose: 'http.request', injection: 'gateway' }],
    resources: { cpu: '500m', memory: '512Mi', concurrency: 4 },
    audit: { required_level: 'detailed' },
    exceptions: [
      { reason: '遗留路径兼容', owner: 'u-1024', expires_at: '2026-08-16T00:00:00Z', approval_ref: 'chg-0091' },
    ],
    version: 7,
    status: 'effective',
    enforcement_mode: 'block',
  },
  {
    policy_id: 'pol-incident-responder',
    selector: { agent_ids: ['ast-02k8w1b3m7'] },
    process: { run_as: '1000:1000', forbid_privilege_escalation: true },
    model_routing: { allowed_models: ['hermes-lite'] },
    version: 3,
    status: 'approved',
    enforcement_mode: 'warn',
  },
  {
    policy_id: 'pol-data-analyst-draft',
    selector: { agent_ids: ['ast-03q4z9p6c2'] },
    version: 1,
    status: 'draft',
    enforcement_mode: 'audit_only',
    unsupported_by_backend: ['filesystem'],
  },
];

const enforcementTag: Record<DesiredPolicy['enforcement_mode'], string> = {
  audit_only: 'tag-info',
  warn: 'tag-warn',
  block: 'tag-err',
};

const statusTag: Partial<Record<DesiredPolicy['status'], string>> = {
  effective: 'tag-ok',
  approved: 'tag-info',
  draft: '',
  proposed: 'tag-info',
  rollback_pending: 'tag-warn',
  rolled_back: 'tag-err',
  failed: 'tag-err',
  rejected: 'tag-err',
};

const columns: TableColumn<DesiredPolicy>[] = [
  { key: 'policy_id', header: '策略 ID', render: (p) => <span className="mono">{p.policy_id}</span> },
  {
    key: 'selector',
    header: '作用范围',
    render: (p) => (
      <>
        <span className="mono">{p.selector.agent_ids.join(', ')}</span>
        {p.selector.environment_ids ? (
          <span className="tag">{p.selector.environment_ids.join(', ')}</span>
        ) : null}
      </>
    ),
  },
  { key: 'version', header: '版本', render: (p) => `v${p.version}` },
  {
    key: 'status',
    header: '状态',
    render: (p) => <span className={`tag ${statusTag[p.status] ?? ''}`}>{p.status}</span>,
  },
  {
    key: 'enforcement',
    header: '执行档位',
    render: (p) => (
      <span className={`tag ${enforcementTag[p.enforcement_mode]}`}>{p.enforcement_mode}</span>
    ),
  },
  {
    key: 'network',
    header: '网络规则',
    render: (p) => (p.network ? `${p.network.length} 条` : '—'),
  },
  {
    key: 'unsupported',
    header: 'unsupported',
    render: (p) =>
      p.unsupported_by_backend && p.unsupported_by_backend.length > 0 ? (
        <span className="tag tag-warn">{p.unsupported_by_backend.join(', ')}</span>
      ) : (
        '—'
      ),
  },
];

export default function PoliciesPage() {
  const policies = useApiList<DesiredPolicy>('/policies', PLACEHOLDER_POLICIES);

  return (
    <section>
      <PageHeader
        title="策略中心"
        description="后端无关的期望安全状态（DesiredPolicy，设计文档 §14.1）：文件系统、网络、进程、模型路由、工具、数据范围与凭据注入约束，按 enforcement_mode 渐进执行。"
        connection={policies.status}
        connectionError={policies.error}
      />
      {policies.status === 'disconnected' ? (
        <DisconnectedNotice error={policies.error} onRetry={policies.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={policies.rows}
        rowKey={(p) => `${p.policy_id}:${p.version}`}
      />
    </section>
  );
}
