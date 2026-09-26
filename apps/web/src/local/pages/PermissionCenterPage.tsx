import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import SimpleTable, { type TableColumn } from '@/components/SimpleTable';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import { canBatchRevoke, type GrantBatchPlan, type GrantBatchResult } from '../grantBatch';
import { grantStatusLabel, grantTag, platformLabel } from '../format';
import type { Grant } from '../types';

const outcomeLabels = { revoked: '已撤权', already_revoked: '已处于撤权状态（未重复写入）', conflict: '版本已变，请重新预览', unavailable: '结果未知，请核查授权与审计' };

export default function PermissionCenterPage() {
  const { actorId } = useLocalSession();
  const [rows, setRows] = useState<Grant[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [platform, setPlatform] = useState('');
  const [showEnded, setShowEnded] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [plan, setPlan] = useState<GrantBatchPlan | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<GrantBatchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const generation = useRef(0);
  const previewHeading = useRef<HTMLHeadingElement>(null);
  const load = useCallback(async () => {
    const current = ++generation.current;
    setLoading(true);
    try {
      const data = await localApi.grants();
      if (current !== generation.current) return;
      setRows(data.grants); setError(''); setLoadError('');
    } catch (err) {
      if (current !== generation.current) return;
      const message = err instanceof Error ? err.message : '读取失败';
      setRows([]); setError(message); setLoadError(message);
    } finally { if (current === generation.current) setLoading(false); }
  }, []);
  useEffect(() => { void load(); return () => { generation.current++; }; }, [load]);
  useEffect(() => { if (plan) previewHeading.current?.focus(); }, [plan]);
  const visible = rows.filter((g) => (showEnded || !['revoked', 'rejected'].includes(g.status))
    && (!platform || platform === g.platform)
    && `${g.subject.id} ${g.grant_id} ${g.skill?.skill_id ?? ''}`.toLowerCase().includes(query.toLowerCase()));
  const selectable = visible.filter(canBatchRevoke);
  const hiddenCount = [...selected].filter((id) => !visible.some((g) => g.grant_id === id)).length;
  const allVisibleSelected = selectable.length > 0 && selectable.every((g) => selected.has(g.grant_id));
  const changeSelection = (next: Set<string>) => { setSelected(next); setPlan(null); setConfirmed(false); setResult(null); setError(''); };
  const toggle = (id: string) => { const next = new Set(selected); if (next.has(id)) next.delete(id); else next.add(id); changeSelection(next); };
  const preview = async () => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setPlan(null); setResult(null); setConfirmed(false);
    try {
      const targets = rows.filter((g) => selected.has(g.grant_id) && canBatchRevoke(g));
      if (targets.length !== selected.size || !targets.length || targets.length > 50) throw new Error('选择已过期或超过 50 项，请刷新后重新选择。');
      setPlan(await localApi.previewGrantBatch(targets.map((g) => ({ grant_id: g.grant_id, expected_revision: g.state_revision! })), actorId));
    } catch (err) { setError(err instanceof Error ? err.message : '预览失败'); }
    finally { setBusy(false); inFlight.current = false; }
  };
  const apply = async () => {
    if (!plan || !confirmed || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError('');
    try {
      const outcome = await localApi.applyGrantBatch(plan);
      setResult(outcome); setSelected(new Set()); setPlan(null); setConfirmed(false);
      await load();
    } catch (err) {
      setError(`${err instanceof Error ? err.message : '请求失败'}。部分操作可能已提交，请刷新核查，或在预览有效期内显式重试同一批次；不会自动重复提交。`);
    } finally { setBusy(false); inFlight.current = false; }
  };
  const columns: TableColumn<Grant>[] = [
    { key: 'select', header: <label><input type="checkbox" aria-label="选择当前筛选的所有可撤权项" checked={allVisibleSelected}
      disabled={busy || loading || !selectable.length} onChange={() => {
        const next = new Set(selected); selectable.forEach((g) => { if (allVisibleSelected) next.delete(g.grant_id); else next.add(g.grant_id); }); changeSelection(next);
      }} /> 本页</label>, render: (g) => <input type="checkbox" aria-label={`选择授权 ${g.subject.id} ${g.grant_id}`}
        checked={selected.has(g.grant_id)} disabled={busy || loading || !canBatchRevoke(g)} onChange={() => toggle(g.grant_id)} /> },
    { key: 'subject', header: '授权对象 / Skill', render: (g) => <><strong>{g.subject.id}</strong><br />
      <small>{g.skill?.skill_id ? `Skill：${g.skill.skill_id}` : '主体授权；未证明具体 Skill 调用归属'}</small><details><summary>授权标识</summary><code>{g.grant_id}</code></details></> },
    { key: 'platform', header: '框架', render: (g) => platformLabel(g.platform) },
    { key: 'tools', header: '工具范围', render: (g) => (g.hermes_toolset_allowlist ?? g.openclaw_tool_policy?.allow)?.join('、') || '查看资源明细' },
    { key: 'status', header: '授权状态', render: (g) => <span className={grantTag(g.status)}>{grantStatusLabel(g.status)}</span> },
    { key: 'expiry', header: '授权期限', render: (g) => g.expires_at ? new Date(g.expires_at).toLocaleString() : '未设期限' },
    { key: 'edit', header: '管理', render: (g) => <Link className="btn btn-sm" to={`/grants?grant=${encodeURIComponent(g.grant_id)}`}>资源、审批与详情</Link> },
  ];
  return <section>
    <PageHeader kicker="个人管理" icon="permissions" title="权限管理" description="查看智能体与 Skill 的授权，勾选后批量撤权；调整工具、读写目录、网络和期限请进入详情。"
      connection={loading ? 'loading' : loadError ? 'disconnected' : 'connected'} connectionError={loadError}
      actions={<button className="btn" disabled={busy || loading} onClick={() => { changeSelection(new Set()); void load(); }}>刷新授权</button>} />
    <p className="notice">声明需要 ≠ 用户批准 ≠ 已验证生效。撤权会影响所有引用该授权的运行身份，包括共享使用者；不会删除 Skill、终止所有进程或撤回已执行的副作用。</p>
    <div className="toolbar">
      <label className="field">搜索对象或授权<input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="角色、Skill 或授权标识" /></label>
      <label className="field">框架<select value={platform} onChange={(e) => setPlatform(e.target.value)}><option value="">全部框架</option>{[...new Set(rows.map((g) => g.platform))].sort().map((p) => <option key={p} value={p}>{platformLabel(p)}</option>)}</select></label>
      <label><input type="checkbox" checked={showEnded} onChange={(e) => setShowEnded(e.target.checked)} /> 显示已结束授权</label>
    </div>
    <div className="toolbar" aria-label="批量操作">
      <span role="status">已选 {selected.size} 项{hiddenCount ? `（其中 ${hiddenCount} 项在筛选外）` : ''}，每批最多 50 项</span>
      <button className="btn" disabled={busy || !selected.size} onClick={() => changeSelection(new Set())}>清空选择</button>
      <button className="btn btn-primary" disabled={busy || loading || !selected.size || selected.size > 50 || !actorId.trim()} onClick={() => void preview()}>{busy ? '处理中…' : '预览批量撤权'}</button>
    </div>
    {error ? <p className="action-error" role="alert">{error}</p> : null}
    {plan ? <div className="card">
      <h2 ref={previewHeading} tabIndex={-1}>确认撤销 {plan.items.length} 项授权</h2>
      <p>以下完整授权将变为“已撤权”，不会只撤销当前页面可见的某个使用者。此操作不能直接恢复；需要重新生成并审批授权。</p>
      <ul>{plan.items.map((item) => <li key={item.grant_id}>{platformLabel(item.platform)} / {item.subject_id}：{grantStatusLabel(item.status)} → 已撤权<br /><code>{item.grant_id}</code>（版本 {item.expected_revision}）</li>)}</ul>
      <p>操作者：{plan.actor_id}；预览有效至 {new Date(plan.expires_at).toLocaleTimeString()}。执行时版本变化的项目将拒绝修改；本批非原子操作，可能部分成功。</p>
      <p>批次：<code>{plan.batch_id}</code></p>
      <label><input type="checkbox" checked={confirmed} disabled={busy} onChange={(e) => setConfirmed(e.target.checked)} /> 我已核对完整对象及共享影响，确认撤权</label>
      <div className="toolbar"><button className="btn" disabled={busy} onClick={() => { setPlan(null); setConfirmed(false); }}>取消</button>
        <button className="btn btn-primary" disabled={!confirmed || busy || plan.actor_id !== actorId.trim()} onClick={() => void apply()}>{busy ? '正在逐项撤权…' : '确认执行撤权'}</button></div>
    </div> : null}
    {result ? <div className="card" role="status"><h2>批量操作结果</h2><p>批次：<code>{result.batch_id}</code></p>
      <ul>{result.items.map((item) => <li key={item.grant_id}><code>{item.grant_id}</code>：{outcomeLabels[item.status]}</li>)}</ul>
      <p>成功项已写入授权审计；失败项请核查后重新选择，不会回滚已成功的撤权。</p>
      <Link to={`/settings?batch=${encodeURIComponent(result.batch_id)}#operation-audit`}>查看此批次操作审计</Link>
    </div> : null}
    <div className="card"><SimpleTable columns={columns} rows={visible} rowKey={(g) => g.grant_id} emptyText={loading ? '正在读取授权…' : error ? '读取不可用，请重试。' : '暂无匹配授权。可从“我的智能体”选择对象，检查后创建待审批授权。'} /></div>
    <details className="card"><summary>高级管理与验证</summary><div className="toolbar">
      <Link to="/grants">完整授权工作台</Link><Link to="/permissions">声明 / 观察 / 生效事实</Link><Link to="/bindings">运行时绑定与接入验证</Link>
    </div></details>
  </section>;
}
