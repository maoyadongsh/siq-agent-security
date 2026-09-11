import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { localApi } from '../api';
import { grantStatusLabel } from '../format';
import { useLocalSession } from '../session';
import type { Admission, Grant, RuntimeIdentity } from '../types';
import GrantResourceDialog from './GrantResourceDialog';
import GrantScopeSummary from './GrantScopeSummary';
import { skillInstallErrorText } from '../skillInstall';
import type { SkillRuntimeReadiness } from '../types';

// Keep editor state above the preview Modal, so only one focus trap is open.
export function useInstancePermissions(instanceId: string, operationBusy = false, requiredGrantId?: string) {
  const { actorId, setActorId } = useLocalSession();
  const [actor, setActor] = useState(actorId);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [admissions, setAdmissions] = useState<Admission[]>([]);
  const [identities, setIdentities] = useState<RuntimeIdentity[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [admissionId, setAdmissionId] = useState('');
  const [reviewed, setReviewed] = useState('');
  const [withdraw, setWithdraw] = useState(false);
  const [ttl, setTtl] = useState(28800);
  const [preparing, setPreparing] = useState(false);
  const [duration, setDuration] = useState('86400');
  const draftRequests = useRef(new Map<string, string>());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [mutationBusy, setBusy] = useState(false);
  const busy = mutationBusy || operationBusy;
  const submitting = useRef(false);
  const [importReadiness, setImportReadiness] = useState<SkillRuntimeReadiness | null>(null);
  const [importError, setImportError] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadedFor, setLoadedFor] = useState('');
  const [error, setError] = useState('');
  const closeEditor = useCallback(() => setEditingId(null), []);
  const subject = instanceId ? `hri-${instanceId.slice(3)}` : '';
  const identity = loadedFor === instanceId ? identities.find((item) => item.instance_id === instanceId && item.status !== 'revoked') : undefined;
  const eligible = grants.filter((item) => item.platform === 'hermes' && item.subject.type === 'agent_instance' && item.subject.id === subject
    && ['pending_approval', 'approved', 'deployed', 'effective'].includes(item.status));
  const currentGrant = grants.find((item) => item.grant_id === identity?.grant_ref.grant_id);
  const changing = preparing || !!(requiredGrantId && identity && identity.grant_ref.grant_id !== requiredGrantId);
  const selected = identity && !changing ? currentGrant : eligible.find((item) => item.grant_id === (requiredGrantId ?? selectedId));
  const imported = selected?.admission_id.startsWith('adm-si-') ?? false;
  const importPrepared = imported && importReadiness?.status === 'prepared' && importReadiness.grant.grant_id === selected?.grant_id && importReadiness.state_revision === selected?.state_revision;
  const reviewKey = selected ? `${selected.grant_id}:${selected.state_revision}` : '';
  useEffect(() => { setPreparing(false); }, [instanceId]);
  const refresh = () => { setReviewed(''); setWithdraw(false); setAttempt((n) => n + 1); };
  useEffect(() => {
    setLoadedFor(''); setReviewed(''); setWithdraw(false); setEditingId(null);
    if (!instanceId) return;
    let active = true;
    setLoading(true); setError('');
    Promise.all([localApi.grants(), localApi.admissions(), localApi.runtimeIdentities()]).then(([g, a, i]) => {
      if (!active) return;
      setGrants(g.grants); setAdmissions(a.admissions.filter((item) => item.verdict !== 'quarantine' && !item.admission_id.startsWith('adm-si-')));
      setIdentities(i.items); setLoadedFor(instanceId);
      setSelectedId((current) => requiredGrantId ?? (g.grants.some((item) => item.grant_id === current && item.subject.id === subject) ? current
        : g.grants.find((item) => item.subject.id === subject && ['pending_approval', 'approved', 'deployed', 'effective'].includes(item.status))?.grant_id ?? ''));
      setAdmissionId((current) => a.admissions.some((item) => item.admission_id === current && item.verdict !== 'quarantine' && !item.admission_id.startsWith('adm-si-')) ? current
        : a.admissions.find((item) => item.verdict !== 'quarantine' && !item.admission_id.startsWith('adm-si-'))?.admission_id ?? '');
    }).catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : '无法读取实例权限'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [instanceId, subject, attempt, requiredGrantId]);
  useEffect(() => {
    setImportReadiness(null); setImportError('');
    if (!imported || !selected || loadedFor !== instanceId) return;
    const controller = new AbortController();
    localApi.skillGrantReadiness(selected.grant_id, controller.signal).then((result) => {
      if (!controller.signal.aborted) setImportReadiness(result);
    }).catch((err: unknown) => { if (!controller.signal.aborted) setImportError(skillInstallErrorText(err)); });
    return () => controller.abort();
  }, [imported, selected?.grant_id, selected?.state_revision, loadedFor, instanceId, attempt]);
  const keepGrant = (grant: Grant) => {
    setGrants((current) => [...current.filter((item) => item.grant_id !== grant.grant_id), grant]);
    setSelectedId(grant.grant_id); setReviewed('');
  };
  const run = async (work: () => Promise<void>) => {
    if (submitting.current || busy || loading || !actor.trim()) return;
    submitting.current = true;
    setBusy(true); setError('');
    try { await work(); setActorId(actor.trim()); }
    catch (err) { setError(err instanceof Error && err.message === 'runtime_identity_no_tools' ? '此授权没有可运行工具，请重新起草并确认所需权限。' : `${err instanceof Error ? err.message : '操作未完成'} 请刷新状态并重新核对。`); }
    finally { submitting.current = false; setBusy(false); }
  };
  const fork = async (source: Grant) => {
    if (source.state_revision === undefined) throw new Error('请重新读取源授权');
    const key = `${source.grant_id}:${source.state_revision}:${actor.trim()}`;
    let requestId = draftRequests.current.get(key);
    if (!requestId) { requestId = `gd-${crypto.randomUUID().replaceAll('-', '')}`; draftRequests.current.set(key, requestId); }
    const out = await localApi.draftGrant(source.grant_id, source.state_revision, actor.trim(), requestId);
    keepGrant({ ...out.grant, state_revision: out.state_revision });
    draftRequests.current.delete(key); setPreparing(true); setEditingId(out.grant.grant_id);
  };
  const forkDraft = (source: Grant) => run(() => fork(source));
  const saveExpiry = () => run(async () => {
    if (!selected || selected.status !== 'pending_approval' || selected.state_revision === undefined) return;
    const out = await localApi.setGrantExpiry(selected.grant_id, selected.state_revision, actor.trim(), duration === 'unlimited' ? null : Number(duration));
    keepGrant({ ...out.grant, state_revision: out.state_revision });
  });
  const createDraft = () => run(async () => {
    if (!admissionId || !instanceId) return;
    const out = await localApi.createGrant({ admission_id: admissionId, platform: 'hermes', subject_id: subject, redact_secrets: true });
    const created = { ...out.grant, state_revision: out.state_revision };
    if (created.status !== 'pending_approval') { await fork(created); return; }
    keepGrant(created); setEditingId(created.grant_id);
  });
  const approveAndDeploy = () => run(async () => {
    if (!selected || imported || reviewed !== reviewKey || selected.state_revision === undefined) return;
    let grant = selected;
    if (grant.status === 'pending_approval') {
      const challenge = await localApi.grantAction(grant.grant_id, 'challenge', { expected_revision: grant.state_revision });
      if (!challenge.challenge) throw new Error('无法准备权限确认');
      const out = await localApi.grantAction(grant.grant_id, 'approve', {
        expected_revision: grant.state_revision, actor_id: actor.trim(), channel: 'console', challenge_id: challenge.challenge.challenge_id, nonce: challenge.challenge.nonce,
      });
      if (!out.grant) throw new Error('未返回批准结果');
      grant = { ...out.grant, state_revision: out.state_revision }; keepGrant(grant);
    }
    if (grant.status !== 'approved' || grant.state_revision === undefined) return;
    const out = await localApi.grantAction(grant.grant_id, 'deploy', { expected_revision: grant.state_revision, actor_id: actor.trim() });
    if (!out.grant) throw new Error('未返回应用结果');
    keepGrant({ ...out.grant, state_revision: out.state_revision });
  });
  const issue = () => run(async () => {
    if (!selected || selected.state_revision === undefined || reviewed !== reviewKey || identity || (imported && !importPrepared)) return;
    const out = await localApi.createRuntimeIdentity(instanceId, selected.grant_id, selected.state_revision, actor.trim(), ttl);
    setIdentities((current) => [...current, out.identity]); setPreparing(false);
  });
  const stop = () => run(async () => {
    if (!identity || !withdraw) return;
    await localApi.revokeRuntimeIdentity(identity.identity_id, actor.trim());
    setIdentities((current) => current.map((item) => item.identity_id === identity.identity_id ? { ...item, status: 'revoked' } : item));
    setWithdraw(false); setReviewed('');
  });
  const scope = (value: Grant | undefined, label: string) => <GrantScopeSummary grant={value} label={label} />;
  const panel = <section className="instance-permission-panel" aria-label="实例权限设置" aria-busy={busy || loading}>
    <h3>实例权限</h3>
    <p>先核对权限，再确认接入。这里配置实例可用范围，实际调用的 Skill 归属仍待验证。</p>
    {loading ? <p role="status">正在读取检查结果和权限…</p> : null}
    {loadedFor === instanceId && identity ? <>
      <p role="status">{identity.status === 'issued' ? (changing ? '当前仍使用旧授权，新权限尚未接入。' : imported && !importPrepared ? '正在核验安装权限，暂不能预览接入。' : '已有可用授权，可以预览接入配置。') : '原有授权已失效，请先停用旧身份，再重新设置。'}</p>
      {scope(currentGrant, '当前实例权限')}
      {imported && !changing && importError ? <p role="alert">{importError}</p> : null}
      {currentGrant && !requiredGrantId ? <button type="button" className="btn" disabled={busy || !actor.trim()} onClick={() => forkDraft(currentGrant)}>调整当前权限</button> : null}
      {!requiredGrantId ? <button type="button" className="btn" disabled={busy} onClick={() => { setPreparing((value) => !value); setReviewed(''); }}>{changing ? '返回当前接入' : '选择其他授权'}</button> : null}
      {changing ? <p>新草稿尚未替换当前权限。先完成编辑和批准，再停用旧身份；切换后请重新开启原平台会话。</p> : null}
      <label><input type="checkbox" checked={withdraw} disabled={busy} onChange={(event) => setWithdraw(event.target.checked)} />确认停用，后续工具调用将被阻止</label>
      <button type="button" className="btn" disabled={busy || !withdraw || !actor.trim()} onClick={stop}>停用此实例权限</button>
    </> : null}
    {loadedFor === instanceId && (!identity || changing) ? <>
      {eligible.length ? <div className="field"><label htmlFor="instance-grant">已有实例授权</label>
        <select id="instance-grant" value={requiredGrantId ?? selectedId} disabled={busy || !!requiredGrantId} onChange={(event) => { setSelectedId(event.target.value); setReviewed(''); }}>
          <option value="">选择授权</option>{eligible.map((grant) => <option key={grant.grant_id} value={grant.grant_id}>{admissions.find((a) => a.admission_id === grant.admission_id)?.skill_name ?? '实例授权'} · {grantStatusLabel(grant.status)}</option>)}
        </select></div> : null}
      {!requiredGrantId ? <details open={!selected}><summary>从已有检查结果起草权限</summary>
        {admissions.length ? <><div className="field"><label htmlFor="instance-admission">参考检查结果</label>
          <select id="instance-admission" value={admissionId} disabled={busy} onChange={(event) => setAdmissionId(event.target.value)}>{admissions.map((item) => <option key={item.admission_id} value={item.admission_id}>{item.skill_name} · {item.content_hash.slice(0, 8)}</option>)}</select></div>
          <button type="button" className="btn" disabled={busy || !admissionId || !actor.trim()} onClick={createDraft}>起草并编辑实例权限</button></>
          : <p>还没有可用检查结果，请先在<Link to="/agents">资产管理</Link>中检查 Skill。</p>}
      </details> : null}
      {requiredGrantId && !selected ? <p role="alert">此次安装对应的授权不可用，请关闭并重新查询安装结果。</p> : null}
      {scope(selected, identity ? '准备替换的权限' : '待接入权限')}
      {selected ? <>
        {!requiredGrantId && (selected.status === 'pending_approval' ? <>
          <button type="button" className="btn" disabled={busy} onClick={() => setEditingId(selected.grant_id)}>编辑权限范围</button>
          <div className="field"><label htmlFor="instance-grant-duration">新授权有效期</label>
            <select id="instance-grant-duration" value={duration} disabled={busy} onChange={(event) => setDuration(event.target.value)}>
              <option value="3600">从现在起 1 小时</option><option value="86400">从现在起 1 天</option><option value="2592000">从现在起 30 天</option><option value="unlimited">不设置到期时间</option>
            </select></div>
          <button type="button" className="btn" disabled={busy || !actor.trim()} onClick={saveExpiry}>保存新授权有效期</button>
          <p>仅点击保存才修改上方到期时间；批准仍需重新核对。</p>
        </> : <button type="button" className="btn" disabled={busy || !actor.trim()} onClick={() => forkDraft(selected)}>基于此授权重新起草</button>)}
        {selected.overlap_conflicts?.some((item) => item.resolution === 'unresolved') ? <p role="alert">存在权限冲突，请在授权页面处理后刷新。</p> : <>
          <label><input type="checkbox" disabled={busy} checked={reviewed === reviewKey} onChange={(event) => setReviewed(event.target.checked ? reviewKey : '')} />我已核对以上权限范围</label>
          {imported && !importPrepared ? <p role="status">{importError || (importReadiness?.status === 'no_tools' ? '此授权没有可运行工具。' : '请从对应安装结果准备实例权限，再刷新此处状态。')} <Link to={importReadiness ? `/grants?install_id=${encodeURIComponent(importReadiness.install_id)}&grant=${encodeURIComponent(selected.grant_id)}` : `/grants?grant=${encodeURIComponent(selected.grant_id)}`}>查看安装与授权</Link></p> : !imported && ['pending_approval', 'approved'].includes(selected.status) ? <button type="button" className="btn" disabled={busy || reviewed !== reviewKey || !actor.trim()} onClick={approveAndDeploy}>确认权限并应用授权</button> : <>
            {identity ? <p role="status">新授权已准备好。请先确认停用上方旧身份，再签发新身份并确认接入；切换期间工具调用会被阻止。</p> : null}
            <div className="field"><label htmlFor="instance-session-ttl">单次会话最长运行时间</label><select id="instance-session-ttl" value={ttl} disabled={busy} onChange={(event) => setTtl(Number(event.target.value))}><option value={3600}>1 小时</option><option value={28800}>8 小时</option><option value={86400}>24 小时</option></select></div>
            <button type="button" className="btn btn-primary" disabled={busy || !!identity || reviewed !== reviewKey || !actor.trim()} onClick={issue}>使用此授权并准备接入</button>
          </>}
        </>}
      </> : null}
    </> : null}
    <div className="field"><label htmlFor="instance-actor">本次操作者</label><input id="instance-actor" maxLength={128} value={actor} disabled={busy} onChange={(event) => setActor(event.target.value)} /></div>
    {error ? <p role="alert" className="action-error">{error}</p> : null}
    <button type="button" className="btn" disabled={busy || loading} onClick={refresh}>刷新权限状态</button>
  </section>;
  return { panel, busy, editing: editingId !== null, identityId: !changing && (!imported || importPrepared) && identity?.status === 'issued' && (!requiredGrantId || identity.grant_ref.grant_id === requiredGrantId) ? identity.identity_id : '',
    editor: editingId ? <GrantResourceDialog grantId={editingId} onClose={closeEditor} onSaved={(grant) => { keepGrant(grant); setEditingId(null); }} /> : null };
}
