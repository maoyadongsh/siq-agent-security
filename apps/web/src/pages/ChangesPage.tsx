import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { useApiList } from '@/hooks/useApiList';
import type { ChangeRequest } from '@/api/types';

/** placeholder 数据（Phase 1；联调后由 /changes 返回） */
const PLACEHOLDER_CHANGES: ChangeRequest[] = [
  {
    change_id: 'chg-0091',
    policy_id: 'pol-legal-contract-review',
    change_type: 'update',
    summary: '续期 fs.write 例外（遗留路径兼容）',
    status: 'pending',
    requested_by: 'u-1024',
    created_at: '2026-08-12T15:20:00Z',
    reason: '风险中心 fnd-002：例外即将过期',
  },
  {
    change_id: 'chg-0092',
    policy_id: 'pol-incident-responder',
    change_type: 'rollback',
    summary: '回滚 process.run_as（1000:1000 → 65532:65532）',
    status: 'approved',
    requested_by: 'u-2048',
    approved_by: 'u-0001',
    created_at: '2026-08-11T09:44:00Z',
    applied_at: '2026-08-11T09:52:00Z',
  },
  {
    change_id: 'chg-0093',
    change_type: 'emergency',
    summary: '紧急阻断 data_analyst_ghost 的凭据工具调用',
    status: 'deploying',
    requested_by: 'u-0001',
    created_at: '2026-08-12T16:01:00Z',
    reason: '风险中心 fnd-001',
  },
  {
    change_id: 'chg-0094',
    policy_id: 'pol-data-analyst-draft',
    change_type: 'create',
    summary: 'data_analyst_ghost 策略草稿 → approved',
    status: 'rejected',
    requested_by: 'u-1024',
    approved_by: 'u-0001',
    created_at: '2026-08-09T08:30:00Z',
  },
];

const typeTag: Record<ChangeRequest['change_type'], string> = {
  create: 'tag-ok',
  update: 'tag-info',
  delete: 'tag-err',
  rollback: 'tag-warn',
  emergency: 'tag-err',
};

const statusTag: Record<ChangeRequest['status'], string> = {
  pending: 'tag-warn',
  approved: 'tag-info',
  rejected: 'tag-err',
  deploying: 'tag-info',
  deployed: 'tag-ok',
  failed: 'tag-err',
  rolled_back: 'tag-err',
};

const columns: TableColumn<ChangeRequest>[] = [
  { key: 'change_id', header: '变更 ID', render: (c) => <span className="mono">{c.change_id}</span> },
  {
    key: 'type',
    header: '类型',
    render: (c) => <span className={`tag ${typeTag[c.change_type]}`}>{c.change_type}</span>,
  },
  { key: 'summary', header: '摘要', render: (c) => <span title={c.reason}>{c.summary ?? '—'}</span> },
  { key: 'target', header: '对象', render: (c) => c.policy_id ?? c.agent_id ?? '—' },
  {
    key: 'status',
    header: '状态',
    render: (c) => <span className={`tag ${statusTag[c.status]}`}>{c.status}</span>,
  },
  { key: 'created_at', header: '提交时间', render: (c) => c.created_at },
  {
    key: 'requested_by',
    header: '申请人',
    render: (c) => <span className="mono">{c.requested_by ?? '—'}</span>,
  },
];

export default function ChangesPage() {
  const changes = useApiList<ChangeRequest>('/changes', PLACEHOLDER_CHANGES);

  return (
    <section>
      <PageHeader
        title="变更中心"
        description="策略与资产变更的申请、审批与执行记录（设计文档 §14.3）：变更需可审计、可回滚。"
        connection={changes.status}
        connectionError={changes.error}
      />
      {changes.status === 'disconnected' ? (
        <DisconnectedNotice error={changes.error} onRetry={changes.reload} />
      ) : null}
      <SimpleTable
        columns={columns}
        rows={changes.rows}
        rowKey={(c) => c.change_id}
      />
    </section>
  );
}
