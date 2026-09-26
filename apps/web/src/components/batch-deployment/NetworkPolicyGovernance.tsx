import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useConsoleContext } from '@/components/ConsoleContext';
import { useApiList } from '@/hooks/useApiList';
import NetworkRevokePanel from './NetworkRevokePanel';
import NetworkRevokeRecovery from './NetworkRevokeRecovery';
import NetworkBatchRevoke, { NetworkBatchRecovery } from './NetworkBatchRevoke';
import { canManageNetwork, policyChoices } from './policyChoices';
import './batch-deployment.css';

function PolicyPicker() {
  const list = useApiList<unknown>('/policies', []);
  const [id, setId] = useState('');
  const [query, setQuery] = useState('');
  const [batch, setBatch] = useState(false);
  const [params] = useSearchParams();
  const { items, invalidCount } = policyChoices(list.rows);
  const visible = items.filter(item => `${item.name} ${item.id}`.toLowerCase().includes(query.trim().toLowerCase()));
  const current = items.find(item => item.id === id);
  const pendingRecovery = params.has('revoke_request') || params.has('revoke_batch');
  if (list.status === 'loading') return <p role="status">正在读取期望策略…</p>;
  if (list.status !== 'connected') return <div role="alert">无法读取策略列表，不表示没有策略。<button type="button" className="btn" onClick={list.refresh}>重试策略列表</button></div>;
  return <div className="network-policy-picker">
    <p>已加载 {list.rows.length} 条策略记录，不代表组织全量。{list.coverageText}</p>
    {invalidCount ? <p role="alert">有 {invalidCount} 条异常或重复记录不可选择，请核对列表数据。</p> : null}
    {list.error ? <p role="alert">{list.error}；已保留已加载记录。</p> : null}
    <button type="button" className="btn" disabled={pendingRecovery} aria-pressed={batch} onClick={() => setBatch(value => !value)}>{batch ? '切换单策略申请' : '切换跨策略批量申请'}</button>
    {batch ? <NetworkBatchRevoke policies={items} /> : items.length ? <>
      <label>查找期望策略<input type="search" value={query} onChange={e => setQuery(e.target.value)} /></label>
      <label>选择期望策略<select value={id} disabled={pendingRecovery} onChange={e => setId(e.target.value)}>
        <option value="">请明确选择策略版本</option>
        {current && !visible.some(item => item.id === current.id) ? <option value={current.id}>{current.name} · v{current.version}（筛选外已选）</option> : null}
        {visible.map(item => <option value={item.id} key={item.id}>{item.name} · v{item.version}</option>)}
      </select></label>
      {!visible.length ? <p>当前筛选无匹配项；已选版本保留。</p> : null}
    </> : <p>{invalidCount ? '没有可安全选择的记录。' : '当前返回的策略列表为空。'}</p>}
    {list.hasMore ? <button type="button" className="btn" disabled={list.loadingMore || pendingRecovery} onClick={list.loadMore}>{list.loadingMore ? '正在加载更多…' : '加载更多策略'}</button> : null}
    {!batch && current ? <NetworkRevokePanel key={current.id} policyId={current.id} /> : null}
  </div>;
}

function Governance() {
  const [open, setOpen] = useState(false);
  const [params] = useSearchParams();
  const policy = params.get('revoke_policy');
  const request = params.get('revoke_request');
  return <section className="card network-policy-governance" aria-label="期望网络权限管理">
    <h2>管理期望网络权限</h2>
    <p>下方权限事实用于观察，不直接作为授权修改依据。请选择期望策略，申请撤除其网络允许项；仍需审批、影响核对和部署验证。</p>
    <p>策略清单为当前组织范围，不随上方同步环境自动缩小；策略可能影响多个运行对象。</p>
    {policy && request ? <NetworkRevokeRecovery key={`${policy}:${request}`} policyId={policy} requestKey={request} /> : null}
    {params.get('revoke_batch') ? <NetworkBatchRecovery key={params.get('revoke_batch')} requestKey={params.get('revoke_batch')!} /> : null}
    <button type="button" className="btn" aria-expanded={open} onClick={() => setOpen(true)} disabled={open}>选择策略并申请撤除</button>
    {open ? <PolicyPicker /> : null}
  </section>;
}

export default function NetworkPolicyGovernance() {
  const { data: context, status } = useConsoleContext();
  if (status !== 'ready' || !canManageNetwork(context) || !context) return null;
  return <Governance key={`${context.tenant.id}:${context.actor.type}:${context.actor.id}`} />;
}
