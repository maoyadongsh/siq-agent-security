import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import PageHeader from '@/components/PageHeader';
import { LocalApiError, localApi } from '../api';
import { grantStatusLabel } from '../format';
import { skillInstallErrorText } from '../skillInstall';
import { comparisonMatchesPlan, sameUpdateValue } from '../skillUpdate';
import { useLocalSession } from '../session';
import GrantScopeSummary from '../components/GrantScopeSummary';
import type { Grant, SkillInstallationRecord, SkillUpdateComparison, SkillUpdateContent, SkillUpdatePlan, SkillUpdateStageRequest, SkillUpdateView } from '../types';

const labels: Record<string, string> = { confirmed: '已记录确认，等待准备新版', removing_previous: '旧权限或旧副本处理未完成', installing_candidate: '旧副本已移除，等待发布新版', recovery_required: '更新中断，需要核对恢复', updated_unverified: '已记录新版文件发布完成', aborted: '已记录更新终止' };
const settings: Record<string, string> = { default_effect: '默认权限效果', enforcement_mode: '执行模式', expires_at: '授权到期时间', hermes_toolset_allowlist: 'Hermes 工具集合', openclaw_tool_policy: 'OpenClaw 工具策略' };
const contentLabel = (v: SkillUpdateContent | null) => v === null ? '不存在' : v.kind === 'directory' ? '目录' : `${v.bytes} 字节${v.executable ? ' · 可执行' : ''} · ${v.sha256.slice(0, 12)}`;
const mismatch = () => new Error('skill_install_incompatible_response');
function Comparison({ data }: { data: SkillUpdateComparison }) {
  return <section className="panel import-panel update-comparison" aria-labelledby="update-comparison-heading">
    <h2 id="update-comparison-heading">内容与权限差异</h2>
    <p>比较时间：{new Date(data.checked_at).toLocaleString()}。以原签名安装清单为基线，不以用户修改后的文件作为旧版本。</p>
    <h3>内容变化 · {data.content_changes_total} 项</h3>
    {data.content_changes_truncated ? <p role="alert">仅展示前 200 项内容变化，请审阅完整候选后决定。</p> : null}
    {!data.content_changes_total ? <p>完整候选清单未发现内容变化，仍需核对权限。</p> : null}
    <ul className="import-files">{data.content_changes.map((change) => <li key={change.path_digest}>
      <strong>{change.before === null ? '新增' : change.after === null ? '移除' : '修改'} · {change.path_display}</strong>
      <span>原版本：{contentLabel(change.before)}</span><span>新版本：{contentLabel(change.after)}</span>
    </li>)}</ul>
    <h3>权限规则变化 · {data.permission_changes_total} 项</h3>
    {data.permission_changes_truncated ? <p role="alert">仅展示前 200 项规则变化，下方同时列出两份授权范围。</p> : null}
    {!data.permission_changes_total ? <p>未发现权限规则变化。</p> : null}
    <ul className="import-files">{data.permission_changes.map((change, index) => <li key={index}>
      <strong>{change.change === 'added' ? '新增规则' : '移除规则'} · {change.rule.effect === 'deny' ? '拒绝' : '允许'}</strong>
      <span>{change.rule.domain} · {change.rule.action} · {change.rule.resource.value}</span>
      {change.rule.conditions ? <span>条件：{JSON.stringify(change.rule.conditions)}</span> : null}
    </li>)}</ul>
    <p>其他设置变化：{data.settings_changed.length ? data.settings_changed.map((key) => settings[key]).join('、') : '无'}。变化不自动获得批准。</p>
    <div className="update-scope-columns"><section><GrantScopeSummary grant={data.previous_grant} label="原授权范围" /><p>执行模式：{data.previous_grant.enforcement_mode}</p><p>工具集合：{data.previous_grant.hermes_toolset_allowlist?.join('、') || '无'}</p></section>
      <section><GrantScopeSummary grant={data.candidate_grant} label="新授权范围" /><p>执行模式：{data.candidate_grant.enforcement_mode}</p><p>工具集合：{data.candidate_grant.hermes_toolset_allowlist?.join('、') || '无'}</p></section></div>
  </section>;
}
export default function SkillUpdatesPage() {
  const { actorId, status } = useLocalSession();
  const [params, setParams] = useSearchParams();
  const installId = params.get('install_id') ?? '', updateId = params.get('update_id') ?? '';
  const [record, setRecord] = useState<SkillInstallationRecord | null>(null);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [candidate, setCandidate] = useState('');
  const [comparison, setComparison] = useState<SkillUpdateComparison | null>(null);
  const [plan, setPlan] = useState<SkillUpdatePlan | null>(null);
  const [view, setView] = useState<SkillUpdateView | null>(null);
  const [stageRequest, setStageRequest] = useState<SkillUpdateStageRequest | null>(null);
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const [confirmed, setConfirmed] = useState(false), [recoverConfirmed, setRecoverConfirmed] = useState(false);
  const [expired, setExpired] = useState(false);
  const active = useRef<AbortController | null>(null);
  const working = useRef(false);
  const preparedReview = useRef<{ signature: string; comparison: SkillUpdateComparison } | null>(null);
  const chosen = view?.claim.plan ?? plan;
  useEffect(() => {
    if (!chosen) { setExpired(false); return; }
    const delay = Date.parse(chosen.expires_at) - Date.now();
    setExpired(delay <= 0);
    const timer = setTimeout(() => setExpired(true), Math.max(0, delay));
    return () => clearTimeout(timer);
  }, [chosen]);
  const assertOriginal = (p: SkillUpdatePlan) => { if (installId && p.record.install_id !== installId) throw mismatch(); };
  const read = async (controller: AbortController, allowPlan: boolean) => {
    try {
      const current = await localApi.skillUpdate(updateId, controller.signal);
      assertOriginal(current.claim.plan);
      if (!controller.signal.aborted) { setView(current); setRecord(current.claim.plan.record); }
    } catch (err) {
      if (!allowPlan || !(err instanceof LocalApiError) || err.status !== 404) throw err;
      const current = await localApi.skillUpdatePlan(updateId, controller.signal);
      assertOriginal(current);
      if (!controller.signal.aborted) { setPlan(current); setRecord(current.record);
        const reviewed = preparedReview.current;
        if (reviewed?.signature === current.signature && comparisonMatchesPlan(reviewed.comparison, current)) setComparison(reviewed.comparison); }
    }
  };
  useEffect(() => {
    const controller = new AbortController(); active.current?.abort(); active.current = controller;
    working.current = true; setBusy(true); setMessage(''); setView(null); setPlan(null); setComparison(null); setRecord(null); setGrants([]); setCandidate(''); setStageRequest(null); setConfirmed(false); setRecoverConfirmed(false);
    const load = async () => {
      if (updateId) { await read(controller, true); return; }
      if (!/^sin-[a-f0-9]{64}$/.test(installId)) throw mismatch();
      const [removal, candidates] = await Promise.all([localApi.skillRemoval(installId, controller.signal), localApi.grants(controller.signal)]);
      if (removal.status !== 'not_requested') throw new Error('skill_install_removal_pending');
      if (!controller.signal.aborted) { setRecord(removal.record); setGrants(candidates.grants); }
    };
    void load().catch((err: unknown) => { if (!controller.signal.aborted) setMessage(skillInstallErrorText(err)); }).finally(() => {
      if (active.current === controller && !controller.signal.aborted) { working.current = false; setBusy(false); }
    });
    return () => { controller.abort(); active.current?.abort(); };
    // Only URL identity starts a new workflow; local response state never reloads it.
  }, [installId, updateId]);
  const run = async (action: (controller: AbortController) => Promise<void>) => {
    if (working.current) return;
    const controller = new AbortController(); active.current?.abort(); active.current = controller;
    working.current = true; setBusy(true); setMessage(''); setConfirmed(false); setRecoverConfirmed(false);
    try { await action(controller); }
    catch (err) { if (!controller.signal.aborted) setMessage(skillInstallErrorText(err)); }
    finally { if (active.current === controller && !controller.signal.aborted) { working.current = false; setBusy(false); } }
  };
  const refresh = () => run(async (controller) => {
    preparedReview.current = null; setView(null); setPlan(null); setComparison(null);
    await read(controller, true);
  });
  const compare = () => run(async (controller) => {
    const original = plan?.record ?? record;
    if (!original?.operation) throw mismatch();
    setComparison(null); setStageRequest(null);
    const latest = await localApi.grants(controller.signal);
    const g = latest.grants.find((item) => item.grant_id === (plan?.candidate_grant_id ?? candidate));
    if (!g || !Number.isSafeInteger(g.state_revision)) throw mismatch();
    const result = await localApi.compareSkillUpdate(original.install_id, { schema_version: 'local-skill-update-compare/v1', operation_signature: original.operation.signature, candidate_grant_id: g.grant_id, expected_candidate_revision: g.state_revision! }, controller.signal);
    if (!sameUpdateValue(result.record, original) || plan && !comparisonMatchesPlan(result, plan)) throw mismatch();
    if (!controller.signal.aborted) { setComparison(result); setGrants(latest.grants); }
  });
  const prepare = () => run(async (controller) => {
    if (!comparison?.record.operation || comparison.candidate_grant.status !== 'approved') throw mismatch();
    const previous = await localApi.skillRemoval(comparison.record.install_id, controller.signal);
    if (previous.status !== 'not_requested' || previous.state_revision !== comparison.previous_revision || previous.grant?.signature !== comparison.previous_grant.signature || !sameUpdateValue(previous.record, comparison.record)) throw mismatch();
    const request: SkillUpdateStageRequest = stageRequest ?? { schema_version: 'local-skill-update-stage-create/v1', request_id: 'up-' + crypto.randomUUID().replaceAll('-', ''), operation_signature: comparison.record.operation.signature,
      candidate_grant_id: comparison.candidate_grant.grant_id, expected_candidate_revision: comparison.candidate_revision, expected_previous_revision: comparison.previous_revision,
      expected_binding_signature: previous.binding_signature, actor_id: actorId.trim() };
    setStageRequest(request);
    const result = await localApi.prepareSkillUpdate(comparison.record.install_id, request, controller.signal);
    if (!comparisonMatchesPlan(comparison, result.plan)) throw mismatch();
    if (!controller.signal.aborted) { preparedReview.current = { signature: result.plan.signature, comparison }; setParams({ install_id: result.plan.record.install_id, update_id: result.plan.update_id }); }
  });
  const write = (recover: boolean) => {
    if (!chosen || recover && (!view || !recoverConfirmed) || !recover && !confirmed) return;
    const original = chosen, prior = view;
    void run(async (controller) => {
      setView(null); setPlan(null); setComparison(null);
      try {
        const result = recover && prior ? await localApi.recoverSkillUpdate({ schema_version: 'local-skill-update-recover/v1', update_id: original.update_id, claim_signature: prior.claim.signature, actor_id: prior.claim.actor_id, confirm_recovery: true }, controller.signal)
          : await localApi.commitSkillUpdate({ schema_version: 'local-skill-update-commit/v1', update_id: original.update_id, plan_signature: original.signature, actor_id: original.actor_id, confirm_update: true }, controller.signal);
        if (!sameUpdateValue(result.claim.plan, original)) throw mismatch();
        if (!controller.signal.aborted) setView(result);
      } catch (err) {
        if (controller.signal.aborted) return;
        try { await read(controller, false); }
        catch (readError) { if (!controller.signal.aborted) { setView(null); setPlan(null); setMessage(skillInstallErrorText(readError) + ' 当前结果无法确认，请重新查询原更新。未自动重发。'); } return; }
        if (!controller.signal.aborted) setMessage(skillInstallErrorText(err) + ' 已只读查询原更新，未自动重发。');
      }
    });
  };
  const candidates = grants.filter((g) => record && g.platform === record.plan.platform && g.subject?.type === 'agent_instance' && g.subject.id === record.plan.instance_id.replace(/^hi-/, 'hri-') && g.grant_id !== record.plan.grant_id && g.admission_id?.startsWith('adm-si-') && ['draft', 'pending_approval', 'approved'].includes(g.status));
  const canContinue = view ? !view.result && (view.status !== 'recovery_required' || view.installation?.status === 'installed_unverified') && (!expired || view.installation?.status === 'installed_unverified') : !!plan && !!comparison && comparisonMatchesPlan(comparison, plan) && !expired;
  return <section className="local-imports-page skill-updates-page">
    <PageHeader title="更新 Skill" kicker="AGENTSHIELD" icon="shield" description="先审阅候选变化，再确认切换。更新不会自动启用新版本的运行权限。" connection={status ? 'connected' : 'loading'}
      actions={<Link className="btn btn-sm" to={installId ? `/installed-skills?install_id=${encodeURIComponent(installId)}` : '/installed-skills'}>返回安装记录</Link>} />
    {busy ? <p role="status">正在检查或处理更新，请稍候…</p> : null}
    {message ? <p className="action-error" role="alert">{message}</p> : null}
    {record ? <section className="panel import-panel"><h2>{record.plan.directory_name}</h2><p>{record.plan.target_display}</p>
      <p>原副本：<code>{record.plan.source.artifact_digest}</code></p></section> : null}
    {!updateId && record ? <section className="panel import-panel"><h2>选择已导入的候选版本</h2>
      <p>先导入新版并为同一实例准备独立权限。候选未批准时可查看差异，批准后才可准备更新。</p>
      <Link to="/skill-imports" target="_blank" rel="noopener noreferrer">导入新版并准备权限（新窗口）</Link>
      <label className="update-candidate-label" htmlFor="update-candidate">候选权限</label><select id="update-candidate" aria-label="候选权限" value={candidate} disabled={busy} onChange={(event) => { setCandidate(event.target.value); setComparison(null); setStageRequest(null); setConfirmed(false); }}>
        <option value="">请选择候选</option>{candidates.map((g) => <option key={g.grant_id} value={g.grant_id}>{new Date(g.created_at).toLocaleString()} · {grantStatusLabel(g.status)} · {g.grant_id.slice(-8)}</option>)}</select>
      {!candidates.length ? <p>尚无符合条件的独立候选权限。准备后刷新本页即可读取。</p> : null}
      <div className="import-actions"><button type="button" className="btn" disabled={busy || !candidate} onClick={() => void compare()}>比较候选变化</button></div>
    </section> : null}
    {comparison ? <Comparison data={comparison} /> : null}
    {comparison && !updateId ? <section className="panel import-panel"><h2>准备更新副本</h2>
      <p>准备不会修改旧版本或撤销旧权限。接下来还需明确确认切换。</p>
      {comparison.candidate_grant.status !== 'approved' ? <p>新权限尚未批准。<Link to={`/grants?grant=${encodeURIComponent(comparison.candidate_grant.grant_id)}`} target="_blank" rel="noopener noreferrer">审阅并批准候选权限（新窗口）</Link>，随后重新比较变化。</p> : null}
      <button type="button" className="btn" disabled={busy || comparison.candidate_grant.status !== 'approved' || !actorId.trim()} onClick={() => void prepare()}>{stageRequest ? '重试原准备请求' : '准备更新副本'}</button>
    </section> : null}
    {chosen ? <section className="panel import-panel update-confirmation"><h2>{view ? labels[view.status] : '更新副本已准备'}</h2>
      <p>新副本：<code>{chosen.candidate_source.artifact_digest}</code> · {chosen.file_count} 个文件 · {chosen.total_bytes} 字节</p>
      {!view?.result ? <><p>确认期限：{new Date(chosen.expires_at).toLocaleString()}。{expired ? '计划已过期，不能新发布；可查询并恢复原事务。' : '继续或刷新不会延长期限。'}</p>
        <p><strong>{chosen.revoke_previous_grant ? '切换会撤销旧版本对应的授权，相关旧会话不能继续使用它。' : '旧授权正在关联另一份安装，本次保留该授权，仅替换所选副本。'}</strong></p>
        <p>新版本需单独准备实例权限；失败恢复不复活旧授权。用户新增或修改的文件会保留。</p>
        <p>原计划操作者：{chosen.actor_id}</p>
        {plan && !view ? <><p>请重新核对本计划的候选差异后确认。</p><button type="button" className="btn" disabled={busy || expired} onClick={() => void compare()}>重新核对计划差异</button></> : null}
        {view ? <p role="status">{view.status === 'confirmed' ? '已收到原确认；尚未记录旧副本移除。可按原范围继续，或终止本次更新。' : view.status === 'removing_previous' ? '旧副本处理已开始。请核对新增、修改或归属不明的内容，保留需要的文件后再继续。' : view.installation?.status === 'installed_unverified' ? '已有新版安装成功记录，可补记更新结果，不会再次安装。' : '旧副本已移除；若无法继续，请恢复未完成操作。旧权限不会重新启用。'}</p> : null}
        <label className="install-confirmation"><input type="checkbox" checked={confirmed} disabled={busy || !canContinue} onChange={(event) => setConfirmed(event.target.checked)} />我已核对更新范围，确认按原计划执行</label>
        <div className="import-actions"><button type="button" className="btn btn-primary" disabled={busy || !confirmed || !canContinue} onClick={() => write(false)}>{view ? '按原确认继续更新' : '确认更新 Skill'}</button></div>
        {view ? <><label className="install-confirmation"><input type="checkbox" checked={recoverConfirmed} disabled={busy} onChange={(event) => setRecoverConfirmed(event.target.checked)} />我已核对现场，确认恢复未完成操作</label>
          <p>尚未开始移除会终止并保留旧版本；已经开始则完成撤权和可证归属的清理。已成功发布的新版本不会因恢复被卸载。</p>
          <button type="button" className="btn" disabled={busy || !recoverConfirmed} onClick={() => write(true)}>恢复未完成的更新</button></> : null}
      </> : <><p role="status">{labels[view.status]} · {new Date(view.result.recorded_at).toLocaleString()}</p>
        {view.status === 'updated_unverified' ? <><p>这是文件发布的历史结果，运行保护仍需单独验证。</p><Link className="btn" to={`/grants?grant=${encodeURIComponent(chosen.candidate_grant_id)}&install_id=${encodeURIComponent(view.installation!.install_id)}`}>查看新版并准备实例权限</Link></> : <p>{view.removal ? '旧副本已移除，旧授权不会恢复。需要安装时请重新审阅候选。' : '本次更新未开始移除旧副本；其当前内容和权限以重新检查为准。'}</p>}
      </>}
      <details><summary>更新记录与授权引用</summary><p>更新编号：<code>{chosen.update_id}</code></p><p>新权限：<code>{chosen.candidate_grant_id}</code></p>
        <Link to={`/grants?grant=${encodeURIComponent(chosen.candidate_grant_id)}`} target="_blank" rel="noopener noreferrer">查看新授权记录（新窗口）</Link></details>
    </section> : null}
    {updateId ? <div className="import-actions"><button type="button" className="btn" disabled={busy} onClick={() => void refresh()}>重新查询原更新</button>
      <Link className="btn" to={`/skill-updates?install_id=${encodeURIComponent(installId || record?.install_id || '')}`}>返回候选选择</Link></div> : null}
  </section>;
}
