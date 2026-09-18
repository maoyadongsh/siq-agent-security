import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { localApi } from '../api';
import { useLocalSession } from '../session';
import { newImportId } from '../skillImports';
import { platformLabel } from '../format';
import { installDirectoryValid, matchesInstallAuthority, skillInstallErrorText, skillInstallScopeLabel, skillInstallRequest } from '../skillInstall';
import type { Grant, ImportPermissionSource, SkillInstallPlan, SkillInstallRequest, SkillInstallationTargets } from '../types';

export default function SkillInstallPreview({ grant, source, skillName, onOperation }: { grant: Grant; source: ImportPermissionSource; skillName: string; onOperation: (message?: string, pending?: boolean) => void }) {
  const [params, setParams] = useSearchParams();
  const installId = params.get('install_id') ?? '';
  const [confirmed, setConfirmed] = useState(false);
  const planId = params.get('install_plan') ?? '';
  const { actorId } = useLocalSession();
  const [directory, setDirectory] = useState(() => installDirectoryValid(skillName) ? skillName : '');
  const [pending, setPending] = useState<SkillInstallRequest | null>(null);
  const [plan, setPlan] = useState<SkillInstallPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [epoch, setEpoch] = useState(0);
  const [now, setNow] = useState(Date.now);
  const workBuddy = grant.platform === 'workbuddy';
  const instanceId = grant.subject.id.replace(/^hri-/, 'hi-');
  const [targets, setTargets] = useState<SkillInstallationTargets | null>(null);
  const [targetId, setTargetId] = useState('');
  const [targetsBusy, setTargetsBusy] = useState(false);
  const [targetsError, setTargetsError] = useState('');
  const [targetsEpoch, setTargetsEpoch] = useState(0);
  useEffect(() => {
    setConfirmed(false); setTargets(null); setTargetsError('');
    if (!workBuddy) { setTargetId(''); return; }
    const controller = new AbortController(); setTargetsBusy(true);
    localApi.skillInstallationTargets(instanceId, controller.signal).then((catalog) => {
      if (controller.signal.aborted) return;
      setTargets(catalog);
      setTargetId((previous) => catalog.targets.some((target) => target.available && target.target_id === previous) ? previous : '');
    }).catch((err: unknown) => { if (!controller.signal.aborted) { setTargetId(''); setTargetsError(skillInstallErrorText(err)); } })
      .finally(() => { if (!controller.signal.aborted) setTargetsBusy(false); });
    return () => controller.abort();
  }, [workBuddy, instanceId, targetsEpoch]);
  const active = useRef<AbortController | null>(null);
  const submitting = useRef(false);
  useEffect(() => () => {
    active.current?.abort();
    if (submitting.current) onOperation('提交已中断，请重新查询原操作结果。');
  }, [onOperation]);
  useEffect(() => {
    if (!planId || installId) return;
    const controller = new AbortController();
    setRestoring(true); setConfirmed(false); setPlan(null); setError(null);
    localApi.installPlan(planId, controller.signal).then((value) => {
      if (controller.signal.aborted) return;
      if (!matchesInstallAuthority(value, grant, source)) throw new Error('skill_install_incompatible_response');
      setPlan(value); setDirectory(value.directory_name); setNow(Date.now());
      if (value.schema_version === 'local-skill-install-plan/v2') setTargetId(value.target_ref.target_id);
    }).catch((err: unknown) => { if (!controller.signal.aborted) setError(skillInstallErrorText(err)); })
      .finally(() => { if (!controller.signal.aborted) setRestoring(false); });
    return () => controller.abort();
  }, [planId, installId, epoch, grant, source]);
  useEffect(() => {
    if (!plan) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [plan]);
  const working = busy || restoring;
  const selectedTarget = targets?.targets.find((target) => target.target_id === targetId && target.available);
  const targetReady = !workBuddy || !!selectedTarget && (!plan || plan.schema_version === 'local-skill-install-plan/v2' && plan.target_ref.target_id === selectedTarget.target_id && plan.target_ref.scope === selectedTarget.scope);
  useEffect(() => { setConfirmed(false); }, [actorId]);
  const expired = !!plan && now >= Date.parse(plan.expires_at);
  const prepare = async (original?: SkillInstallRequest) => {
    if (submitting.current || working || grant.state_revision === undefined) return;
    const body = original ?? skillInstallRequest(grant, newImportId().replace(/^si-/, 'is-'), directory, actorId, targets, targetId);
    if (!body || !installDirectoryValid(body.directory_name) || !body.actor_id || !targetReady || targetsBusy ||
      (workBuddy && (body.schema_version !== 'local-skill-install-stage-create/v2' || body.target_id !== targetId))) return;
    setConfirmed(false);
    submitting.current = true; setBusy(true); setError(null); setPlan(null); setPending(body);
    const controller = new AbortController(); active.current = controller;
    try {
      const result = await localApi.createInstallPlan(body, controller.signal);
      if (controller.signal.aborted) return;
      if (!matchesInstallAuthority(result.plan, grant, source)) throw new Error('skill_install_incompatible_response');
      setParams((previous) => {
        const next = new URLSearchParams(previous); next.set('grant', grant.grant_id); next.set('install_plan', result.plan.plan_id); return next;
      });
    } catch (err) { if (!controller.signal.aborted) setError(skillInstallErrorText(err)); }
    finally { submitting.current = false; if (!controller.signal.aborted) setBusy(false); }
  };
  const install = async () => {
    if (submitting.current || working || !plan || expired || !confirmed || !targetReady || targetsBusy || actorId.trim() !== plan.actor_id) return;
    submitting.current = true; setBusy(true); setError(null);
    const controller = new AbortController(); active.current = controller;
    onOperation(undefined, true);
    setParams((previous) => { const next = new URLSearchParams(previous); next.delete('install_plan'); next.set('install_id', plan.plan_id.replace(/^sip-/, 'sin-')); return next; });
    try {
      await localApi.applySkillInstall({ schema_version: 'local-skill-install-apply/v1', plan_id: plan.plan_id,
        plan_signature: plan.signature, actor_id: plan.actor_id, confirm_install: true }, controller.signal);
      if (!controller.signal.aborted) onOperation();
    } catch (err) { if (!controller.signal.aborted) onOperation(skillInstallErrorText(err)); }
    finally { submitting.current = false; if (!controller.signal.aborted) { setBusy(false); setRestoring(false); } }
  };
  const reset = () => {
    if (working) return;
    setPending(null); setPlan(null); setError(null); setConfirmed(false);
    setParams((previous) => { const next = new URLSearchParams(previous); next.delete('install_plan'); next.set('grant', grant.grant_id); return next; });
  };
  if (installId) return busy ? <p role="status">正在提交安装，请稍候。结果可按原操作编号重新查询。</p> : null;
  return <section className="skill-install-preview" aria-labelledby="install-preview-heading">
    <h3 id="install-preview-heading">安装预览</h3>
    <p className="page-desc">权限已批准。先核对安装位置与内容；生成预览会准备本机暂存副本，尚未安装到 {platformLabel(grant.platform)}。</p>
    <p className="page-desc">目标为此授权绑定的 {platformLabel(grant.platform)} 实例；操作者沿用上方填写的批准人。</p>
    {workBuddy ? <div className="field">
      <label htmlFor="install-target">安装范围与位置</label>
      <select id="install-target" value={targetId} disabled={working || targetsBusy || !!pending || !!planId}
        onChange={(event) => { setTargetId(event.target.value); setConfirmed(false); setPlan(null); setPending(null); setError(null); }}>
        <option value="">请选择用户级或项目级目标</option>
        {targets?.targets.map((target) => <option key={target.target_id} value={target.target_id} disabled={!target.available}>
          {target.scope === 'project' ? '项目级' : '用户级'} · {target.root_display} · {target.target_display}{target.available ? '' : '（当前不可用）'}
        </option>)}
      </select>
      {targetsBusy ? <p role="status">正在核验服务端安装目标…</p> : null}
      {targetsError ? <p role="alert" className="action-error">{targetsError} 未选择其他目录。</p> : null}
      {plan && !targetsBusy && !targetReady ? <p role="alert">原预览目标当前不可用，请保留原记录并重新核验。</p> : null}
      <p className="page-desc">项目级 Skill 写入已登记项目的 .codebuddy/skills。<Link to="/agents">登记项目目录</Link>后返回刷新目标；登记 Skill 目录不等于登记项目。</p>
      <button type="button" className="btn" disabled={working || targetsBusy || !!pending || !!planId} onClick={() => { setConfirmed(false); setTargetsEpoch((value) => value + 1); }}>刷新安装目标</button>
      <p className="page-desc">同名项目 Skill 可能优先于用户 Skill。文件安装不会确认原生启用、缓存刷新或实际选用；项目目录也不构成运行沙箱。</p>
    </div> : null}
    <div className="field"><label htmlFor="install-directory">Skill 安装目录名</label>
      <input id="install-directory" value={directory} onChange={(event) => { setDirectory(event.target.value); setConfirmed(false); }} maxLength={64}
        disabled={working || !!pending || !!planId} aria-describedby="install-directory-help" />
      <p id="install-directory-help" className="page-desc">1–64 个小写字母、数字或连字符，首尾为字母或数字；不能覆盖已有目录。</p>
    </div>
    {error ? <p className="action-error" role="alert">{error}</p> : null}
    {working ? <p role="status">正在核对权限、内容与目标目录…</p> : null}
    {plan ? <div className="install-plan-result">
      <p role="status">{expired ? '预览已到期，请重新准备。' : '预览已核验，尚未安装。'}</p>
      <dl>
        <dt>安装范围</dt><dd>{skillInstallScopeLabel(plan)}</dd>
        <dt>目标位置</dt><dd>{plan.target_display}</dd>
        <dt>待安装文件</dt><dd>{plan.file_count} 个 · {plan.total_bytes.toLocaleString()} 字节</dd>
        <dt>预览到期时间</dt><dd><time dateTime={plan.expires_at}>{new Date(plan.expires_at).toLocaleString()}</time></dd>
        <dt>副本摘要</dt><dd><code>{plan.source.artifact_digest}</code></dd>
        <dt>权限摘要</dt><dd><code>{plan.grant_permission_digest}</code></dd>
      </dl>
      <p className="page-desc">安装会写入上方新目录。完成后仍需平台识别与保护验证，当前不会启用此 Skill 的运行权限。</p>
    </div> : null}
    {plan && !expired ? <div className="field">
      <label className="install-confirmation"><input type="checkbox" checked={confirmed} disabled={working || targetsBusy || !targetReady} onChange={(event) => setConfirmed(event.target.checked)} /> 我已核对安装位置、内容和权限，确认安装</label>
      {actorId.trim() !== plan.actor_id ? <p role="alert">操作者已变化，请恢复为 {plan.actor_id} 或重新准备预览。</p> : null}
    </div> : null}
    <div className="import-actions">
      {plan ? <button type="button" className="btn btn-primary" disabled={working || targetsBusy || !targetReady || expired || !confirmed || actorId.trim() !== plan.actor_id} onClick={() => void install()}>确认安装 Skill</button> : null}
      {!pending && !planId ? <button type="button" className="btn btn-primary" disabled={working || targetsBusy || !targetReady || !installDirectoryValid(directory) || !actorId.trim() || grant.state_revision === undefined} onClick={() => void prepare()}>生成安装预览</button> : null}
      {pending && error && !planId ? <button type="button" className="btn" disabled={working || targetsBusy || !targetReady} onClick={() => void prepare(pending)}>重试原预览请求</button> : null}
      {planId ? <button type="button" className="btn" disabled={working || expired} onClick={() => setEpoch((value) => value + 1)}>重新核验预览</button> : null}
      {pending || planId ? <button type="button" className="btn" disabled={working} onClick={reset}>重新准备预览</button> : null}
    </div>
  </section>;
}
