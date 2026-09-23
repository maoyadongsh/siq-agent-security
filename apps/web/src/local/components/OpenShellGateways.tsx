import { useEffect, useState, type ReactNode } from 'react';
import { localApi } from '../api';
import type { GatewayCatalog, RegisteredGateway } from '../openshellGateways';

const selectionKey = 'siq-openshell-view-gateway';
export default function OpenShellGateways({ children, refreshKey }: { children: (gateway?: RegisteredGateway) => ReactNode; refreshKey: string }) {
  const [catalog, setCatalog] = useState<GatewayCatalog>();
  const [selected, setSelected] = useState(() => { try { return sessionStorage.getItem(selectionKey) ?? ''; } catch { return ''; } });
  const [attempt, setAttempt] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(''); setCatalog(undefined);
    localApi.openshellGateways(controller.signal).then((value) => { if (!controller.signal.aborted) setCatalog(value); })
      .catch(() => { if (!controller.signal.aborted) setError('已登记网关暂时无法读取，请刷新网关列表。'); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [attempt, refreshKey]);
  const gateway = catalog?.items.find((row) => row.gateway_id === selected);
  const unavailable = selected !== '' && !gateway;
  return <div className="block-gap">
    <section aria-label="OpenShell 网关选择">
      <div className="toolbar"><h3>查看 OpenShell 网关</h3><button type="button" className="btn btn-sm" disabled={loading} onClick={() => setAttempt((value) => value + 1)}>刷新网关列表</button></div>
      {loading ? <p role="status">正在读取本机已登记的网关…</p> : null}
      {error ? <p role="alert" className="action-error">{error}</p> : null}
      {catalog?.state === 'unsupported' ? <p>当前 CLI 来源或版本暂不支持已登记网关选择，可继续查看启动时配置的环境。</p> : null}
      {catalog?.state === 'unavailable' ? <p>已登记网关清单未能完整读取，请检查现有 CLI 配置后刷新；此状态不代表没有网关。</p> : null}
      {catalog?.state === 'available' || selected ? <div className="field"><label htmlFor="openshell-gateway-choice">选择已登记网关</label>
        <select id="openshell-gateway-choice" value={selected} disabled={loading} onChange={(event) => {
          const id = event.target.value; setSelected(id);
          try { if (id) sessionStorage.setItem(selectionKey, id); else sessionStorage.removeItem(selectionKey); }
          catch { setError('本次选择可用，但浏览器无法保存；刷新页面后需要重新选择。'); }
        }}>
          <option value="">启动时配置的网关</option>
          {unavailable ? <option value={selected}>上次选择（暂不可用）</option> : null}
          {catalog?.items.map((row) => <option key={row.gateway_id} value={row.gateway_id}>{row.name}{row.native_active ? ' · OpenShell 默认' : ''}</option>)}
        </select></div> : null}
      {gateway ? <p className="page-desc">{gateway.endpoint_display} · 已登记配置。此选择用于查看沙箱和策略；智能体运行位置以实际运行记录为准。</p> : null}
      {!loading && unavailable ? <p role="alert">上次选择的网关暂不可用或登记已变化，请刷新列表或重新选择。</p> : null}
    </section>
    {!unavailable && (!selected || !loading) ? children(gateway) : null}
  </div>;
}
