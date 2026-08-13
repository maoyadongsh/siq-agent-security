import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import DisconnectedNotice from '@/components/DisconnectedNotice';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { api, ApiError } from '@/api/client';
import type { AgentAsset, Evidence } from '@/api/types';

type LoadStatus = 'loading' | 'connected' | 'disconnected';

const statusTag: Record<string, string> = {
  managed: 'tag-ok',
  confirmed: 'tag-ok',
  stale: 'tag-warn',
  candidate: 'tag-warn',
  needs_review: 'tag-warn',
  dismissed: 'tag-err',
  retired: '',
};

const evidenceColumns: TableColumn<Evidence>[] = [
  { key: 'id', header: '证据 ID', render: (e) => <span className="mono">{e.id}</span> },
  { key: 'source_type', header: '来源类型', render: (e) => e.source_type },
  {
    key: 'source_locator',
    header: '来源定位',
    render: (e) => <span title={e.source_locator}>{e.source_locator}</span>,
  },
  { key: 'observed_at', header: '观察时间', render: (e) => e.observed_at },
  { key: 'classification', header: '分类', render: (e) => e.classification },
  {
    key: 'content_hash',
    header: '内容摘要',
    render: (e) => <span className="mono">{e.content_hash.slice(0, 16)}…</span>,
  },
  { key: 'collector_id', header: '采集者', render: (e) => e.collector_id },
];

/** 资产信息行 */
function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

/**
 * 智能体资产详情：拉取 GET /agents/:id 与 GET /agents/:id/evidence 渲染。
 * 后端未运行时保持"未连接"空态（可重试），不阻塞页面。
 */
export default function AgentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<AgentAsset | null>(null);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [reloadSeq, setReloadSeq] = useState(0);

  useEffect(() => {
    if (!id) {
      setStatus('disconnected');
      setError('缺少资产 ID');
      return;
    }
    let cancelled = false;
    setStatus('loading');
    setError(null);

    Promise.allSettled([api.getAgent(id), api.getAgentEvidence(id)]).then(
      ([assetResult, evidenceResult]) => {
        if (cancelled) return;
        if (assetResult.status === 'rejected') {
          setStatus('disconnected');
          setError(
            assetResult.reason instanceof ApiError
              ? `${assetResult.reason.message}（HTTP ${assetResult.reason.status}）`
              : '资产详情加载失败',
          );
          return;
        }
        setAgent(assetResult.value);
        setEvidence(
          evidenceResult.status === 'fulfilled' ? evidenceResult.value : [],
        );
        setStatus('connected');
      },
    );

    return () => {
      cancelled = true;
    };
  }, [id, reloadSeq]);

  return (
    <section>
      <PageHeader
        title={agent?.name ?? '智能体资产详情'}
        description="资产详情：来源候选、纳管状态、角色与关联证据（设计文档 §10）。"
        connection={status}
        connectionError={error}
      />
      {status === 'disconnected' ? (
        <DisconnectedNotice error={error} onRetry={() => setReloadSeq((s) => s + 1)} />
      ) : null}
      {status === 'loading' ? (
        <p className="table-empty">加载中…</p>
      ) : null}
      {status === 'connected' && agent ? (
        <>
          <div className="card">
            <h2>资产信息</h2>
            <dl className="kv-list">
              <InfoRow label="资产 ID" value={<span className="mono">{agent.id}</span>} />
              <InfoRow label="名称" value={agent.name} />
              <InfoRow label="角色" value={agent.role ?? '—'} />
              <InfoRow
                label="状态"
                value={
                  <span className={`tag ${statusTag[agent.status] ?? ''}`}>
                    {agent.status}
                  </span>
                }
              />
              <InfoRow label="框架" value={agent.framework} />
              <InfoRow label="系统" value={agent.system_id ?? '—'} />
              <InfoRow label="负责人" value={agent.owner_user_id ?? '—'} />
              <InfoRow label="来源类型" value={agent.source_type ?? '—'} />
              <InfoRow
                label="来源定位"
                value={<span className="mono">{agent.source_locator ?? '—'}</span>}
              />
              <InfoRow label="更新时间" value={agent.updated_at} />
            </dl>
          </div>
          <div className="card">
            <h2>关联证据（{evidence.length}）</h2>
            <SimpleTable
              columns={evidenceColumns}
              rows={evidence}
              rowKey={(e) => e.id}
              emptyText="暂无关联证据"
            />
          </div>
        </>
      ) : null}
      <p>
        <Link to="/agents">← 返回智能体资产列表</Link>
      </p>
    </section>
  );
}
