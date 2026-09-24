import { useEffect, useState } from 'react';
import { businessNavigation, type BusinessNavigation } from '@/api/businessNavigation';
import type { Evidence } from '@/api/types';
import { inventoryStamp } from '@/api/inventoryReview';

export default function BusinessRunLinks({ assetId, evidence }: { assetId: string; evidence: Evidence[] }) {
  const [value, setValue] = useState<BusinessNavigation | null>(null);
  const [failed, setFailed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let live = true;
    setValue(null); setFailed(false);
    businessNavigation(assetId).then(result => { if (live) setValue(result); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [assetId, retry]);
  return <div className="card">
    <h2>业务运行结果</h2>
    <p>在业务系统中查看，需使用有数据访问权限的业务账号登录。</p>
    {failed ? <p role="alert">暂时无法读取业务入口。<button className="btn" onClick={() => setRetry(n => n + 1)}>重试</button></p>
      : !value ? <p role="status">正在读取业务入口…</p>
      : !value.configured ? <p>尚未连接业务系统，请联系管理员配置业务入口。</p>
      : !value.items.length ? <p>暂无可关联的业务运行记录。</p>
      : <ul>{value.items.map(item => <li key={item.evidence_id}>
        <span>记录时间：{inventoryStamp(evidence.find(row => row.id === item.evidence_id)?.observed_at ?? '')} · </span>
        <a href={item.href} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">查看业务运行结果</a>
        <details><summary>事件编号</summary><span className="mono">{item.event_id}</span></details>
      </li>)}</ul>}
  </div>;
}
