import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { localApi } from '../api';
import type { Receipt } from '../types';
import { useLocalSession } from '../session';
import { actionLabel, actionTag, platformLabel, shortHash } from '../format';

function shortTime(iso: string): string {
  return iso.length >= 19 ? iso.slice(0, 19).replace('T', ' ') : iso;
}

export default function ReceiptsPage() {
  const { actorId } = useLocalSession();
  const [rows, setRows] = useState<Receipt[]>([]);
  const [verified, setVerified] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);
  const [holdErr, setHoldErr] = useState<string | null>(null);

  const load = (announce = false) => {
    setLoading(true);
    localApi
      .receipts()
      .then((data) => {
        setRows([...(data.receipts ?? [])].reverse());
        setVerified(Boolean(data.verified));
        setError(null);
        setLoading(false);
        if (announce) {
          setMsg(data.verified ? '哈希链与签名均通过。' : '验签失败：链断裂或签名不匹配。');
        }
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '加载失败');
        setLoading(false);
      });
  };

  useEffect(() => {
    load(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const resolve = (receiptId: string, approve: boolean) => {
    setHoldErr(null);
    localApi
      .resolveHold(receiptId, approve, actorId)
      .then(() => load(false))
      .catch((err: unknown) => {
        setHoldErr(err instanceof Error ? err.message : '签核失败');
      });
  };

  const columns: TableColumn<Receipt>[] = [
    { key: 'seq', header: 'seq', render: (r) => String(r.seq) },
    {
      key: 'time',
      header: '时间',
      render: (r) => <span className="mono cell-nowrap">{shortTime(r.issued_at)}</span>,
    },
    {
      key: 'action',
      header: '动作',
      render: (r) => (
        <span className={actionTag(r.action)} title={r.action}>
          {actionLabel(r.action)}
        </span>
      ),
    },
    { key: 'tool', header: '工具', render: (r) => r.tool },
    { key: 'plat', header: '平台', render: (r) => platformLabel(r.platform) },
    { key: 'reason', header: '原因', render: (r) => r.reason },
    {
      key: 'advisory',
      header: '建议动作',
      render: (r) =>
        r.advisory_action ? (
          <span className={actionTag(r.advisory_action)} title={r.advisory_action}>
            {actionLabel(r.advisory_action)}
          </span>
        ) : (
          '—'
        ),
    },
    {
      key: 'hash',
      header: 'hash',
      render: (r) => <span className="mono">{shortHash(r.hash, 10)}</span>,
    },
    {
      key: 'hold',
      header: '',
      render: (r) =>
        r.action === 'hold' ? (
          <span className="row-actions">
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={(e) => {
                e.stopPropagation();
                resolve(r.receipt_id, true);
              }}
            >
              放行
            </button>
            <button
              type="button"
              className="btn btn-sm btn-danger"
              onClick={(e) => {
                e.stopPropagation();
                resolve(r.receipt_id, false);
              }}
            >
              拒绝
            </button>
          </span>
        ) : null,
    },
  ];

  return (
    <section>
      <PageHeader
        kicker="AGENTSHIELD"
        icon="audit"
        title="回执"
        description="只追加的哈希链。参数原文不入库；验签在服务端重算，控制台不持有私钥。"
        connection={loading ? 'loading' : error ? 'disconnected' : 'connected'}
        connectionError={error}
        actions={
          <button type="button" className="btn btn-primary" onClick={() => load(true)}>
            <Icon name="shield" size={14} /> 验签
          </button>
        }
      />
      {verified === true ? (
        <div className="scan-result" role="status">
          <p>链完整，签名有效（{rows.length} 条）。</p>
        </div>
      ) : null}
      {verified === false ? (
        <p className="action-error" role="alert">
          验签失败：{msg ?? '链断裂或签名不匹配。'}
        </p>
      ) : null}
      {holdErr ? (
        <p className="action-error" role="alert">
          {holdErr}
        </p>
      ) : null}
      {error ? (
        <div className="notice" role="status">
          <p className="notice-title">加载失败</p>
          <p className="notice-detail">{error}</p>
        </div>
      ) : null}
      <div className="card">
        <SimpleTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.receipt_id}
          emptyText={
            loading
              ? '加载中…'
              : error
                ? '决策 API 不可达，暂时无法读取回执。'
                : '还没有回执。装上适配器后，工具调用会写到这里。'
          }
          rowClassName={(r) => (r.action === 'deny' ? 'row-deny' : undefined)}
        />
      </div>
    </section>
  );
}
