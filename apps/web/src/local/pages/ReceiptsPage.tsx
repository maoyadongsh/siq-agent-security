import { useEffect, useState } from 'react';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { Icon } from '@/components/icons';
import { localApi } from '../api';
import type { Receipt } from '../types';
import { useLocalSession } from '../session';
import { actionTag, shortHash } from '../format';

export default function ReceiptsPage() {
  const { actorId } = useLocalSession();
  const [rows, setRows] = useState<Receipt[]>([]);
  const [verified, setVerified] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

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

  const columns: TableColumn<Receipt>[] = [
    { key: 'seq', header: 'seq', render: (r) => String(r.seq) },
    {
      key: 'action',
      header: '动作',
      render: (r) => <span className={actionTag(r.action)}>{r.action}</span>,
    },
    { key: 'tool', header: '工具', render: (r) => r.tool },
    { key: 'plat', header: '平台', render: (r) => r.platform },
    { key: 'reason', header: '原因', render: (r) => r.reason },
    { key: 'hash', header: 'hash', render: (r) => <span className="mono">{shortHash(r.hash, 10)}</span> },
    {
      key: 'hold',
      header: '',
      render: (r) =>
        r.action === 'hold' ? (
          <span>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={(e) => {
                e.stopPropagation();
                localApi.resolveHold(r.receipt_id, true, actorId).then(() => load(false)).catch((err: unknown) => {
                  setMsg(err instanceof Error ? err.message : '签核失败');
                });
              }}
            >
              放行
            </button>{' '}
            <button
              type="button"
              className="btn btn-sm"
              onClick={(e) => {
                e.stopPropagation();
                localApi.resolveHold(r.receipt_id, false, actorId).then(() => load(false)).catch((err: unknown) => {
                  setMsg(err instanceof Error ? err.message : '签核失败');
                });
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
      {verified === true ? <p className="page-desc">链完整，签名有效。</p> : null}
      {verified === false ? (
        <div className="notice" role="status">
          <p className="notice-title">验签失败</p>
          <p className="notice-detail">{msg}</p>
        </div>
      ) : null}
      {msg && verified !== false ? <p className="page-desc">{msg}</p> : null}
      <div className="card">
        <SimpleTable
          columns={columns}
          rows={rows}
          rowKey={(r) => r.receipt_id}
          emptyText="还没有回执。装上适配器后，工具调用会写到这里。"
          rowClassName={(r) => (r.action === 'deny' ? 'row-deny' : undefined)}
        />
      </div>
    </section>
  );
}
