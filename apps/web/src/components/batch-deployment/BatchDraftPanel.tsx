import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { createBatchDraft, readBatchDraft, readBatchResult, type BatchDraft, type BatchResult } from '@/api/deploymentBatch';
import type { DeploymentSelection } from '@/api/deploymentPreview';
import type { ChangeRequestRow, RuntimeBindingRow } from '@/api/types';
import { addBatchSelection, batchRequestKey } from './selection';
import './batch-deployment.css';
import BatchItemReview from './BatchItemReview';

/** Preview/read only until complete impact disclosure is available. Never executes. */
export default function BatchDraftPanel({ changes, binding }: { changes: ChangeRequestRow[]; binding: RuntimeBindingRow | null }) {
  const [query, setQuery] = useSearchParams();
  const draftId = query.get('batch');
  const [selectedChange, setSelectedChange] = useState('');
  const [items, setItems] = useState<DeploymentSelection[]>([]);
  const [draft, setDraft] = useState<BatchDraft | null>(null);
  const [result, setResult] = useState<BatchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const seq = useRef(0);
  const pending = useRef(false);
  // Same selection retains its draft idempotency key after a lost response.
  const createKey = useRef<string | null>(null);
  const eligible = changes.filter(row => row.status === 'approved' || row.status === 'emergency_applied');

  useEffect(() => {
    const ticket = ++seq.current;
    pending.current = false;
    setDraft(null); setResult(null); setError(''); setBusy(Boolean(draftId));
    if (draftId) {
      void (async () => {
        try {
          const value = await readBatchDraft(draftId);
          if (ticket !== seq.current) return;
          setDraft(value);
          const saved = await readBatchResult(value);
          if (ticket === seq.current) setResult(saved);
        } catch {
          if (ticket === seq.current) setError('暂时无法核对批次或执行记录。请重试查询；不要据此重复执行。');
        } finally { if (ticket === seq.current) setBusy(false); }
      })();
    }
    return () => { seq.current += 1; };
  }, [draftId, retry]);

  function add() {
    if (busy || !binding || !eligible.some(row => row.id === selectedChange)) return;
    try {
      setItems(addBatchSelection(items, { change_request_id: selectedChange, environment_id: binding.environment_id, binding_id: binding.id }));
      createKey.current = null; setError('');
    } catch (e) { setError(e instanceof Error ? e.message : '无法加入批次'); }
  }
  async function preview() {
    if (pending.current || busy || !items.length) return;
    pending.current = true; setBusy(true); setError('');
    const ticket = ++seq.current;
    try {
      createKey.current ??= batchRequestKey();
      const value = await createBatchDraft(items, createKey.current);
      if (ticket !== seq.current) return;
      const next = new URLSearchParams(query); next.set('batch', value.id); setQuery(next);
    } catch {
      if (ticket === seq.current) setError('批次预览未完成，请核对审批、环境及绑定后重试。相同选择重试沿用原请求标识，不会部署。');
    } finally {
      if (ticket === seq.current) { pending.current = false; setBusy(false); }
    }
  }

  return <section className="card batch-deployment" aria-label="批次预览与结果">
    <h2>批次预览与结果</h2>
    <p>最多选择 20 条已批准变更，每条需明确绑定目标。只覆盖已加载变更；审批和目标适用性由后端再次核对。</p>
    <p>当前入口只生成预览、查询结果，不发起执行。共享影响与权限内容的完整确认界面尚未接通。</p>
    {!draftId ? <>
      <label>已批准变更<select aria-label="批次中的变更" value={selectedChange} disabled={busy} onChange={e => setSelectedChange(e.target.value)}>
        <option value="">请选择变更</option>{eligible.map(row => <option key={row.id} value={row.id}>{row.id} · {row.policy_id}</option>)}
      </select></label>
      <p>使用上方明确选中的绑定：{binding ? `${binding.id} / ${binding.backend_target_id}` : '尚未选择'}</p>
      <button type="button" className="btn" onClick={add} disabled={busy || !binding || !selectedChange || items.length >= 20}>加入批次</button>
      <p role="status">已选择 {items.length} 项；切换上方目标不会更改已加入项。</p>
      <ul>{items.map(item => <li key={item.change_request_id}>
        {item.change_request_id} → {item.environment_id} / {item.binding_id}
        <button type="button" className="btn-sm" disabled={busy} aria-label={`移除 ${item.change_request_id}`} onClick={() => {
          setItems(items.filter(value => value.change_request_id !== item.change_request_id)); createKey.current = null;
        }}>移除</button>
      </li>)}</ul>
      <button type="button" className="btn btn-primary" disabled={busy || !items.length} onClick={() => void preview()}>生成批次预览（不部署）</button>
    </> : <>
      <p>批次：<code>{draftId}</code>（地址栏保留批次标识，刷新后重新核对身份和记录）</p>
      <button type="button" className="btn" disabled={busy} onClick={() => setRetry(n => n + 1)}>刷新批次与结果</button>
      <button type="button" className="btn" disabled={busy} onClick={() => {
        const next = new URLSearchParams(query); next.delete('batch'); setItems([]); createKey.current = null; setQuery(next);
      }}>返回选择（不删除历史）</button>
    </>}
    {busy ? <p role="status">正在核对批次…</p> : null}
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    {draft ? <>
      <p>草稿状态：{draft.state === 'expired' ? '已过期，不能用于新执行' : '预览已保存，不等于已执行'}；期限：{draft.expires_at}</p>
      <p>这是历史预览，刷新读取不等于重新验证目标；有效执行仍须逐项复验。</p>
      <ul>{draft.preview.items.map(item => <li key={item.change_id}>
        <strong>{item.policy_name} · v{item.policy_version}</strong>：{item.environment_name} / {item.target}；期望档位 {item.enforcement_mode}；{item.backend === 'fake' ? '测试后端，不证明实际执行' : 'OpenShell'}
        <p>变更 {item.change_id}；绑定 {item.binding_id}</p>
        <BatchItemReview key={`${item.change_id}:${item.preview_digest}`} item={item} />
      </li>)}</ul>
      {!busy && !error && !result ? <p>尚未查询到执行预留；本页不会自动提交或恢复执行。</p> : null}
    </> : null}
    {result ? <>
      <h3>逐项执行记录</h3><p>{result.state === 'unconfirmed' ? '部分结果尚未确认，禁止盲目重试' : result.state === 'needs_attention' ? '存在失败或待处理项' : '结果已记录，不等于整批生效'}</p>
      <ul>{result.items.map(item => <li key={item.id}>{item.change_id}：{item.deployment_status} <Link to={`/changes?change=${encodeURIComponent(item.change_id)}&view=execution&deployment=${encodeURIComponent(item.deployment_id)}`}>查看部署与审计</Link></li>)}</ul>
    </> : null}
  </section>;
}
