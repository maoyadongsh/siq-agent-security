import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { Finding } from '@/api/types';

/** placeholder 数据（Phase 1；联调后由 /findings 返回） */
const PLACEHOLDER_FINDINGS: Finding[] = [
  {
    finding_id: 'fnd-001',
    agent_id: 'ast-03q4z9p6c2',
    title: '未纳管智能体持有凭据类工具权限',
    description: 'data_analyst_ghost 的 OpenShell 策略声明了 credential 域动作，但资产仍处于 needs_review，未见审批记录。',
    severity: 'high',
    status: 'open',
    evidence_ids: ['ev-0004', 'ev-0005'],
    detected_at: '2026-08-11T06:20:00Z',
  },
  {
    finding_id: 'fnd-002',
    agent_id: 'ast-01h2kd93nf',
    title: '策略例外即将过期',
    description: 'fs.write 到 /srv/siq/legal/reviews/ 的 deny 例外将在 3 天内失效。',
    severity: 'medium',
    status: 'investigating',
    evidence_ids: ['ev-0003'],
    detected_at: '2026-08-09T10:05:00Z',
  },
  {
    finding_id: 'fnd-003',
    title: 'Connector 版本落后，缺补丁',
    description: 'docker Connector 版本 v1.1.0 低于最低安全版本 v1.2.0。',
    severity: 'low',
    status: 'open',
    environment_id: 'env-dev-docker',
    evidence_ids: ['ev-0009'],
    detected_at: '2026-08-07T03:41:00Z',
  },
  {
    finding_id: 'fnd-004',
    agent_id: 'ast-02k8w1b3m7',
    title: '委托 token 刷新链路异常',
    description: 'SIQ IAM 未返回 delegated-token（purpose=incident-response），数据范围退化为空。',
    severity: 'critical',
    status: 'investigating',
    evidence_ids: ['ev-0012'],
    detected_at: '2026-08-12T14:12:00Z',
  },
];

const sevTag: Record<Finding['severity'], string> = {
  critical: 'tag-err',
  high: 'tag-err',
  medium: 'tag-warn',
  low: 'tag-info',
  info: '',
};

const statusTag: Record<Finding['status'], string> = {
  open: 'tag-err',
  investigating: 'tag-warn',
  mitigated: 'tag-info',
  accepted: '',
  resolved: 'tag-ok',
};

const columns: TableColumn<Finding>[] = [
  {
    key: 'severity',
    header: '级别',
    render: (f) => <span className={`tag ${sevTag[f.severity]}`}>{f.severity}</span>,
  },
  { key: 'title', header: '风险', render: (f) => <span title={f.description}>{f.title}</span> },
  { key: 'agent', header: '关联资产', render: (f) => f.agent_id ?? f.environment_id ?? '—' },
  {
    key: 'status',
    header: '状态',
    render: (f) => <span className={`tag ${statusTag[f.status]}`}>{f.status}</span>,
  },
  { key: 'detected_at', header: '发现时间', render: (f) => f.detected_at },
  { key: 'evidence', header: '证据', render: (f) => <span className="mono">{f.evidence_ids.length} 条</span> },
];

export default function FindingsPage() {
  const findings = useApiList<Finding>('/findings', PLACEHOLDER_FINDINGS);

  return (
    <section>
      <PageHeader
        title="风险中心"
        description="聚合证据与权限事实的风险结论（Finding）：级别、状态、关联资产与支撑证据。"
        connection={findings.status}
        connectionError={findings.error}
      />
      {findings.status === 'disconnected' ? (
        <DisconnectedNotice error={findings.error} onRetry={findings.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={findings.rows}
        rowKey={(f) => f.finding_id}
      />
    </section>
  );
}
