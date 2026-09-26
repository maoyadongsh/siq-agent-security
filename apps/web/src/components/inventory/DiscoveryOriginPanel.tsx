import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError } from '@/api/client';
import { getDiscoveryOrigin, type DiscoveryOrigin } from '@/api/discoveryOrigin';

export function DiscoveryOriginDetails({ origin }: { origin: DiscoveryOrigin }) {
  if (origin.status === 'legacy_unresolved') return <p>历史资产尚未确认设备归属，不从名称或旧证据猜测来源。</p>;
  if (origin.status === 'source_unavailable') return <p>来源绑定暂不可用，不能据此判断设备不存在或已受保护。</p>;
  return <>
    <dl className="kv-list">
      <dt>发现环境</dt><dd>{origin.environment?.name}</dd>
      <dt>采集设备</dt><dd className="mono">{origin.device?.identity}</dd>
      <dt>设备凭据</dt><dd>{origin.device?.revoked ? '已吊销，仅保留历史来源' : '未吊销，不代表当前在线'}</dd>
    </dl>
    <p>此处证明发现来源，不代表运行时已绑定、权限已生效或攻击已被拦截。</p>
    <Link to="/environments">核对环境与设备接入状态 →</Link>
    <details>
      <summary>来源观察（{origin.observations.length}{origin.observations_truncated ? '，已截断' : ''}）</summary>
      {origin.observations_truncated ? <p>仅展示最近 200 条观察，不是完整历史。</p> : null}
      {!origin.observations.length ? <p>尚无可关联的来源观察，不能据此推断没有风险。</p> : null}
      <ul>{origin.observations.map(o => <li key={o.observation_id}>
        <span className="mono">{o.observation_id}</span> · <time dateTime={o.observed_at}>{o.observed_at}</time>
        <div>证据：<span className="mono">{o.evidence_id}</span></div>
        <div>SHA-256：<span className="mono" style={{ overflowWrap: 'anywhere' }}>{o.content_hash}</span></div>
      </li>)}</ul>
    </details>
  </>;
}

function OriginRequest({ assetId }: { assetId: string }) {
  const [result, setResult] = useState<DiscoveryOrigin>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    getDiscoveryOrigin(assetId).then(value => { if (live) setResult(value); })
      .catch(reason => { if (live) setError(reason instanceof ApiError && reason.status === 403
        ? '当前账号无权读取资产的环境来源，请联系组织管理员。'
        : '资产来源读取失败，当前不能核实设备归属。'); });
    return () => { live = false; };
  }, [assetId, attempt]);
  return <section className="card" aria-label="发现来源">
    <h2>发现来源</h2>
    {error ? <p role="alert">{error} <button className="btn" onClick={() => {
      setResult(undefined); setError(undefined); setAttempt(n => n + 1);
    }}>重试读取来源</button></p> : result ? <DiscoveryOriginDetails origin={result} /> : <p role="status">正在核对资产来源…</p>}
  </section>;
}

export default function DiscoveryOriginPanel({ assetId }: { assetId: string }) {
  return <OriginRequest key={assetId} assetId={assetId} />;
}
