import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { readRevokeRecovery, type RevokeRecovery } from '@/api/networkRevoke';

export default function NetworkRevokeRecovery({ policyId, requestKey }: { policyId: string; requestKey: string }) {
  const [record, setRecord] = useState<RevokeRecovery | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setRecord(null); setBusy(true); setError(false);
    void readRevokeRecovery(policyId, requestKey).then(value => { if (active) setRecord(value); })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [policyId, requestKey, retry]);
  return <section className="card" aria-label="恢复撤除申请">
    <h2>恢复撤除申请</h2>
    <p>只查询原请求，不重新提交或执行。地址栏请求标识不代替当前身份验证。</p>
    {busy ? <p role="status">正在查找原申请…</p> : null}
    {error ? <p role="alert">暂时无法确认原申请：可能仍在处理、连接失败或当前身份无权读取。不能据此判断未提交，请勿另建重复申请。</p> : null}
    {record ? <p role="status">已找到原申请；当前记录状态：{record.change_status}。这不证明撤权效果。<Link to={`/changes?change=${encodeURIComponent(record.change_request_id)}`}>核对审批与部署记录</Link></p> : null}
    <button type="button" className="btn" disabled={busy} onClick={() => setRetry(n => n + 1)}>重新查询原申请</button>
  </section>;
}
