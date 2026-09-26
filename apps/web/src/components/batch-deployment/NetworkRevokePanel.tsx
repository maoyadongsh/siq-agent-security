import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { readRevokeOptions, proposeNetworkRevoke, selectionKey, type RevokeOptions, type RevokeResult } from '@/api/networkRevoke';
import { batchRequestKey } from './selection';

export default function NetworkRevokePanel({ policyId }: { policyId: string }) {
  const [params, setParams] = useSearchParams();
  const [options, setOptions] = useState<RevokeOptions | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(() => params.has('revoke_request'));
  const [error, setError] = useState('');
  const [result, setResult] = useState<RevokeResult | null>(null);
  const pending = useRef(false);
  const generation = useRef(0);
  const key = useRef<string | null>(null);
  const anotherRequest = params.has('revoke_batch') || params.has('revoke_request') && params.get('revoke_request') !== key.current;
  useEffect(() => () => { generation.current += 1; }, []);
  async function load() {
    if (pending.current || uncertain || anotherRequest) return;
    pending.current = true; setBusy(true); setError(''); setOptions(null); setSelected(new Set()); setAck(false);
    const ticket = generation.current;
    try { const value = await readRevokeOptions(policyId); if (ticket === generation.current) setOptions(value); }
    catch { if (ticket === generation.current) setError('无法读取完整、安全的撤除选项，请核对权限及策略配置。'); }
    finally { if (ticket === generation.current) { pending.current = false; setBusy(false); } }
  }
  async function submit() {
    if (pending.current || anotherRequest || !options || !selected.size || !ack || result) return;
    pending.current = true; setBusy(true); setError('');
    const ticket = generation.current;
    try {
      key.current ??= batchRequestKey();
      const next = new URLSearchParams(params);
      next.set('revoke_policy', policyId); next.set('revoke_request', key.current);
      setParams(next, { replace: true });
      const value = await proposeNetworkRevoke(options, options.selections.filter(s => selected.has(selectionKey(s))), key.current);
      if (ticket === generation.current) { setResult(value); setUncertain(false); }
    } catch {
      if (ticket === generation.current) { setUncertain(true); setError('申请结果未确认，选择已锁定。可沿用原请求标识重试；不要另建重复申请。若基线已变化，请先到变更中心核对。'); }
    } finally { if (ticket === generation.current) { pending.current = false; setBusy(false); } }
  }
  const rows = options?.selections.filter(s => `${s.endpoint} ${s.binary_path}`.toLowerCase().includes(query.trim().toLowerCase())) ?? [];
  const hidden = selected.size - rows.filter(s => selected.has(selectionKey(s))).length;
  const changeSelection = (next: Set<string>) => { setSelected(next); setAck(false); key.current = null; };
  return <section className="network-revoke-panel" aria-label="网络权限撤除申请">
    <h3>申请撤除网络允许项</h3>
    <p>只修改期望策略的新版本；仍需独立审批、目标影响确认和部署读回，不代表当前已撤权。</p>
    {!result ? <button type="button" className="btn-sm" disabled={busy || uncertain || anotherRequest} onClick={() => void load()}>读取可撤除项</button> : null}
    {busy ? <p role="status">正在处理申请…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {options && !result ? <>
      <p>策略版本 {options.policy_version}；共 {options.selections.length} 项，仅覆盖此期望策略的网络允许项。</p>
      {options.selections.length ? <>
        <label>筛选网络允许项<input type="search" value={query} onChange={e => setQuery(e.target.value)} /></label>
        <p role="status">已选 {selected.size} 项，筛选外已选 {hidden} 项；最多 256 项。</p>
        <button type="button" className="btn-sm" disabled={busy || uncertain} onClick={() => changeSelection(new Set([...selected, ...rows.map(selectionKey)]))}>选择筛选结果</button>
        <button type="button" className="btn-sm" disabled={busy || uncertain} onClick={() => changeSelection(new Set())}>清空选择</button>
        <ul>{rows.map(s => <li key={selectionKey(s)}><label><input type="checkbox" disabled={busy || uncertain} checked={selected.has(selectionKey(s))} onChange={e => {
          const next = new Set(selected); if (e.target.checked) next.add(selectionKey(s)); else next.delete(selectionKey(s)); changeSelection(next);
        }} />{s.endpoint} · {s.binary_path}</label></li>)}</ul>
        {!rows.length ? <p>当前筛选无匹配项，已选项仍保留。</p> : null}
        <label><input type="checkbox" disabled={busy || uncertain} checked={ack} onChange={e => setAck(e.target.checked)} />我确认对全部已选项创建撤除申请，包括筛选外选中项；不是立即撤权。</label>
        <button type="button" className="btn-sm" disabled={busy || anotherRequest || !ack || !selected.size} onClick={() => void submit()}>{uncertain ? '重试同一申请' : '创建撤除申请（不执行）'}</button>
      </> : <p>此期望策略没有可选网络允许项，不表示运行时没有其他权限。</p>}
    </> : null}
    {anotherRequest || uncertain && !options ? <p>地址栏保留了原请求，请先在上方恢复区核对记录；这里不会另建申请。</p> : null}
    {result ? <p role="status">撤除申请记录已返回，本次未执行。请核对当前审批与部署状态。<Link to={`/changes?change=${encodeURIComponent(result.change_request_id)}`}>查看变更与审批</Link></p> : null}
  </section>;
}
