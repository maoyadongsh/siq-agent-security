import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { readRevokeOptions, selectionKey } from '@/api/networkRevoke';
import { proposeRevokeBatch, readRevokeBatch, type BatchRevokeSelection, type BatchRevokeResult, type BatchRevokeRecovery } from '@/api/networkRevokeBatch';
import type { PolicyChoice } from './policyChoices';
import { batchRequestKey } from './selection';

export function NetworkBatchRecovery({ requestKey }: { requestKey: string }) {
  const [data, setData] = useState<BatchRevokeRecovery | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null); setBusy(true); setError(false);
    void readRevokeBatch(requestKey).then(value => { if (active) setData(value); })
      .catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [requestKey, retry]);
  return <section className="card network-batch-recovery" aria-label="恢复批量撤除申请">
    <h3>恢复批量撤除申请</h3>
    <p>只查询原批次，不重放申请。各项审批状态独立，不证明撤权效果。</p>
    {busy ? <p role="status">正在查询原批次…</p> : null}
    {error ? <p role="alert">暂时无法核对完整批次，可能尚未持久化、连接失败或身份无权读取；不表示没有提交，请勿另建重复申请。</p> : null}
    {data ? <ul>{data.items.map(item => <li key={item.change_request_id}>{item.source_policy_id}：当前状态 {item.change_status} · <Link to={`/changes?change=${encodeURIComponent(item.change_request_id)}`}>查看此项审批与部署</Link></li>)}</ul> : null}
    <button type="button" className="btn" disabled={busy} onClick={() => setRetry(value => value + 1)}>重新查询批次</button>
  </section>;
}

export default function NetworkBatchRevoke({ policies }: { policies: PolicyChoice[] }) {
  const [params, setParams] = useSearchParams();
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [entries, setEntries] = useState<BatchRevokeSelection[]>([]);
  const [ack, setAck] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState<BatchRevokeResult | null>(null);
  const pending = useRef(false);
  const generation = useRef(0);
  const key = useRef<string | null>(null);
  useEffect(() => () => { generation.current += 1; }, []);
  const externalRequest = params.has('revoke_request') || params.has('revoke_batch') && params.get('revoke_batch') !== key.current;
  const frozen = busy || uncertain || !!result || externalRequest;
  const current = policies.filter(policy => chosen.has(policy.id));
  const invalid = current.length !== chosen.size || new Set(current.map(policy => policy.name)).size !== current.length;
  const visible = policies.filter(policy => `${policy.name} ${policy.id}`.toLowerCase().includes(query.trim().toLowerCase()));
  const hidden = chosen.size - visible.filter(policy => chosen.has(policy.id)).length;
  const count = entries.reduce((total, entry) => total + entry.selections.length, 0);
  const complete = entries.length === chosen.size && entries.length > 0 && entries.every(entry => entry.selections.length > 0);
  function choose(id: string, checked: boolean) {
    if (frozen) return;
    const next = new Set(chosen); if (checked) next.add(id); else next.delete(id);
    setChosen(next); setEntries([]); setAck(false); setError('');
  }
  async function load() {
    if (pending.current || frozen || invalid || !chosen.size || chosen.size > 20) return;
    pending.current = true; setBusy(true); setError(''); setEntries([]); setAck(false);
    const ticket = generation.current;
    try {
      const values = await Promise.all(current.map(async policy => {
        const options = await readRevokeOptions(policy.id);
        if (options.policy_version !== policy.version) throw new Error('version mismatch');
        return { options, selections: [] };
      }));
      if (ticket === generation.current) setEntries(values);
    } catch { if (ticket === generation.current) setError('未能读取全部完整选项，未保留部分成功快照；请核对权限、版本和策略支持情况后重试。'); }
    finally { if (ticket === generation.current) { pending.current = false; setBusy(false); } }
  }
  function changeSelections(id: string, keys: Set<string>) {
    if (frozen) return;
    setEntries(values => values.map(entry => entry.options.policy_id === id
      ? { ...entry, selections: entry.options.selections.filter(selection => keys.has(selectionKey(selection))) } : entry));
    setAck(false);
  }
  async function submit() {
    if (pending.current || externalRequest || result || invalid || !complete || count > 512 || !ack) return;
    pending.current = true; setBusy(true); setError('');
    const ticket = generation.current;
    try {
      key.current ??= batchRequestKey();
      const next = new URLSearchParams(params); next.set('revoke_batch', key.current); setParams(next, { replace: true });
      const value = await proposeRevokeBatch(entries, key.current);
      if (ticket === generation.current) { setResult(value); setUncertain(false); }
    } catch { if (ticket === generation.current) { setUncertain(true); setError('批次结果未确认，全部选择已锁定；只能沿用原请求重试或查询原批次，不要另建重复申请。'); } }
    finally { if (ticket === generation.current) { pending.current = false; setBusy(false); } }
  }
  return <section className="network-revoke-panel network-batch-revoke" aria-label="跨策略批量撤除">
    <h3>跨策略批量申请</h3>
    <p>最多 20 份不同名称的策略、512 个网络允许项。整批申请成功或回滚；每项仍需独立审批与部署，不是立即撤权。</p>
    {externalRequest ? <p role="status">请先核对上方原申请恢复记录；当前不允许另建批次。</p> : null}
    <label>筛选批量策略<input type="search" value={query} onChange={event => setQuery(event.target.value)} /></label>
    <p role="status">已选 {chosen.size} 份策略，筛选外已选 {hidden} 份；仅覆盖已加载清单。</p>
    <button type="button" className="btn-sm" disabled={frozen || !chosen.size} onClick={() => {
      if (frozen || pending.current) return;
      setChosen(new Set()); setEntries([]); setAck(false); setError('');
    }}>清空全部策略选择（含筛选外）</button>
    <ul>{visible.map(policy => <li key={policy.id}><label><input type="checkbox" checked={chosen.has(policy.id)} disabled={frozen || chosen.size >= 20 && !chosen.has(policy.id)} onChange={event => choose(policy.id, event.target.checked)} />{policy.name} · v{policy.version} · {policy.id}</label></li>)}</ul>
    {!visible.length ? <p>当前筛选无匹配，已有选择保留。</p> : null}
    {invalid ? <p role="alert">所选记录已变化或包含同名策略的多个版本，请重新选择。</p> : null}
    <button type="button" className="btn" disabled={frozen || !chosen.size || invalid} onClick={() => void load()}>读取全部可撤除项</button>
    {busy ? <p role="status">正在处理批次…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {entries.map(entry => <fieldset key={entry.options.policy_id} disabled={frozen}>
      <legend>{entry.options.policy_id} · v{entry.options.policy_version}</legend>
      <p>只覆盖此期望策略网络允许项，共 {entry.options.selections.length} 项。</p>
      <button type="button" className="btn-sm" onClick={() => changeSelections(entry.options.policy_id, new Set(entry.options.selections.map(selectionKey)))}>选择此策略全部项</button>
      <button type="button" className="btn-sm" onClick={() => changeSelections(entry.options.policy_id, new Set())}>清空此策略选择</button>
      {!entry.options.selections.length ? <p>此策略无可选项，请取消选择该策略；不代表运行时没有权限。</p> : null}
      <ul>{entry.options.selections.map(selection => <li key={selectionKey(selection)}><label><input type="checkbox" checked={entry.selections.some(item => selectionKey(item) === selectionKey(selection))} onChange={event => {
        const next = new Set(entry.selections.map(selectionKey)); if (event.target.checked) next.add(selectionKey(selection)); else next.delete(selectionKey(selection)); changeSelections(entry.options.policy_id, next);
      }} />{selection.endpoint} · {selection.binary_path}</label></li>)}</ul>
    </fieldset>)}
    <p role="status">批量已选 {count} 个网络允许项。</p>
    {count > 512 ? <p role="alert">超过 512 项上限，请减少选择，不能提交。</p> : null}
    {entries.length && !result ? <>
      <label><input type="checkbox" disabled={frozen} checked={ack} onChange={event => setAck(event.target.checked)} />我确认全部策略及选中项，包括筛选外策略；仅提交申请，不立即撤权。</label>
      <button type="button" className="btn" disabled={busy || externalRequest || invalid || !complete || count > 512 || !ack} onClick={() => void submit()}>{uncertain ? '重试原批次申请' : '提交批量撤除申请（不执行）'}</button>
    </> : null}
    {result ? <div role="status"><p>整批申请记录已返回，本次未执行；请逐项核对审批与部署。</p><ul>{result.items.map(item => <li key={item.change_request_id}>{item.source_policy_id} · <Link to={`/changes?change=${encodeURIComponent(item.change_request_id)}`}>查看此项变更</Link></li>)}</ul></div> : null}
  </section>;
}
